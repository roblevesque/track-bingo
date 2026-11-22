from sqlmodel import Session, select

from app.models import Song
from tests.conftest import csrf_token, make_mp3, upload


def songs(app):
    with Session(app.state.engine) as session:
        return session.exec(select(Song).order_by(Song.id)).all()


def upload_titled(client, tmp_path, name, title, artist, tail=b""):
    path = make_mp3(tmp_path / name, title=title, artist=artist)
    return upload(client, name, path.read_bytes() + tail)


def messages(client):
    return client.get("/library").text


def test_a_song_that_looks_like_an_existing_one_is_added_with_a_warning(app, logged_in, tmp_path):
    upload_titled(logged_in, tmp_path, "first.mp3", "Dancing Queen", "ABBA")
    upload_titled(logged_in, tmp_path, "second.mp3", "Dancing Queen (Remastered)", "ABBA", tail=b"\x00" * 10)
    assert len(songs(app)) == 2  # added anyway
    page = messages(logged_in)
    assert "may be a copy of" in page and "Dancing Queen" in page and "Find duplicates" in page


def test_the_same_file_uploaded_twice_is_called_out(app, logged_in, tmp_path):
    data = make_mp3(tmp_path / "plain.mp3").read_bytes()  # no title or artist tags, so the bytes are the same every time
    upload(logged_in, "one.mp3", data)
    upload(logged_in, "two.mp3", data)
    assert len(songs(app)) == 2
    assert "is the same file as" in messages(logged_in)


def test_different_songs_give_no_warning(app, logged_in, tmp_path):
    upload_titled(logged_in, tmp_path, "a.mp3", "Waterloo", "ABBA")
    upload_titled(logged_in, tmp_path, "b.mp3", "Vogue", "Madonna", tail=b"\x00" * 10)
    page = messages(logged_in)
    assert "may be a copy of" not in page and "is the same file as" not in page


def test_duplicates_within_one_upload_are_caught(app, logged_in, tmp_path):
    a = make_mp3(tmp_path / "x.mp3", title="Vogue", artist="Madonna").read_bytes()
    r = logged_in.post("/library/upload", data={"csrf_token": csrf_token(logged_in, "/library")},
                       files=[("files", ("x1.mp3", a, "audio/mpeg")), ("files", ("x2.mp3", a + b"\x00", "audio/mpeg"))],
                       follow_redirects=False)
    assert r.status_code == 303 and len(songs(app)) == 2
    assert "may be a copy of" in messages(logged_in)


def test_the_duplicates_page_lists_groups_and_needs_a_login(app, logged_in, tmp_path, client):
    upload_titled(logged_in, tmp_path, "one.mp3", "Waterloo", "ABBA")
    upload_titled(logged_in, tmp_path, "two.mp3", "Waterloo", "ABBA", tail=b"\x00" * 10)
    upload_titled(logged_in, tmp_path, "three.mp3", "Vogue", "Madonna", tail=b"\x00" * 20)
    page = logged_in.get("/library/duplicates").text
    assert "Same title and artist" in page and page.count("Waterloo") >= 2 and "Vogue" not in page
    assert 'name="back" value="duplicates"' in page
    from tests.conftest import new_player
    assert new_player(app).get("/library/duplicates", follow_redirects=False).status_code in (303, 401)


def test_deleting_from_the_duplicates_page_returns_there(app, logged_in, tmp_path):
    upload_titled(logged_in, tmp_path, "one.mp3", "Waterloo", "ABBA")
    upload_titled(logged_in, tmp_path, "two.mp3", "Waterloo", "ABBA", tail=b"\x00" * 10)
    first = songs(app)[0].id
    r = logged_in.post(f"/library/{first}/delete", data={"csrf_token": csrf_token(logged_in, "/library/duplicates"), "back": "duplicates"},
                       follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/library/duplicates"
    assert len(songs(app)) == 1
    assert "No duplicates found" in logged_in.get("/library/duplicates").text


def test_an_ordinary_delete_still_returns_to_the_library(app, logged_in, tmp_path):
    upload_titled(logged_in, tmp_path, "one.mp3", "Waterloo", "ABBA")
    sid = songs(app)[0].id
    r = logged_in.post(f"/library/{sid}/delete", data={"csrf_token": csrf_token(logged_in, "/library"), "q": "abba"}, follow_redirects=False)
    assert r.headers["location"].startswith("/library?q=abba")
