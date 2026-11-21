"""Cards (formerly tickets), upload tags and progress, default clip length, and the console's lists."""
import re

from sqlmodel import Session

from app.models import AppSetting, Song
from app.services.settings_store import DEFAULT_CLIP_SECONDS, get_clip_seconds
from tests.conftest import all_songs, create_game, csrf_token, game_id_from, make_mp3, seed_songs, upload


def upload_with_tags(client, name, content, tags, xhr=False):
    return client.post(
        "/library/upload",
        data={"csrf_token": csrf_token(client, "/library"), "tags": tags},
        files=[("files", (name, content, "audio/mpeg"))],
        headers={"x-requested-with": "xhr"} if xhr else {},
        follow_redirects=False,
    )


def test_tags_given_at_upload_are_tidied_and_applied(app, logged_in, tmp_path):
    mp3 = make_mp3(tmp_path / "a.mp3", title="One")
    assert upload_with_tags(logged_in, "a.mp3", mp3.read_bytes(), " 80s , Rock,rock ").status_code == 303
    assert all_songs(app)[0].tag_list == ["80s", "rock"]


def test_an_upload_without_tags_has_none(app, logged_in, tmp_path):
    upload(logged_in, "a.mp3", make_mp3(tmp_path / "a.mp3").read_bytes())
    assert all_songs(app)[0].tag_list == []


def test_the_progress_bar_upload_gets_json_and_the_messages_wait_for_the_next_page(app, logged_in, tmp_path):
    mp3 = make_mp3(tmp_path / "a.mp3", title="One")
    response = upload_with_tags(logged_in, "a.mp3", mp3.read_bytes(), "", xhr=True)
    assert response.status_code == 200 and response.json() == {"redirect": "/library"}
    assert "Added 1 song" in logged_in.get("/library").text  # the flash was kept for the page we land on


def test_the_upload_form_offers_tags_progress_and_the_clip_length(logged_in):
    page = logged_in.get("/library").text
    assert 'name="tags"' in page and "data-upload" in page and "upload-progress" in page
    assert 'name="clip_seconds"' in page and f'value="{DEFAULT_CLIP_SECONDS}"' in page


def test_the_default_clip_length_can_be_changed_and_is_checked(app, logged_in):
    def set_length(value):
        return logged_in.post("/library/clip-length", data={"clip_seconds": value, "csrf_token": csrf_token(logged_in, "/library")},
                              follow_redirects=False)
    with Session(app.state.engine) as session:
        assert get_clip_seconds(session) == DEFAULT_CLIP_SECONDS
    assert set_length("20").status_code == 303
    with Session(app.state.engine) as session:
        assert get_clip_seconds(session) == 20
    assert 'value="20"' in logged_in.get("/library").text
    set_length("0")
    set_length("lots")
    with Session(app.state.engine) as session:
        assert get_clip_seconds(session) == 20  # refused values change nothing
        assert session.get(AppSetting, "clip_seconds").value == "20"


def test_the_clip_length_needs_a_csrf_token(app, logged_in):
    response = logged_in.post("/library/clip-length", data={"clip_seconds": "10"}, follow_redirects=False)
    assert response.status_code in (400, 403)


def test_the_edit_page_has_the_position_readout_and_the_auto_fill_controls(app, logged_in, tmp_path):
    upload(logged_in, "a.mp3", make_mp3(tmp_path / "a.mp3", title="One").read_bytes())
    song = all_songs(app)[0]
    page = logged_in.get(f"/library/{song.id}/edit").text
    assert 'id="position"' in page and 'id="auto-fill"' in page and 'id="clip-length"' in page
    assert 'name="auto_fill"' in page and "checked" in page  # on by default


def test_auto_fill_is_remembered_per_song(app, logged_in, tmp_path):
    upload(logged_in, "a.mp3", make_mp3(tmp_path / "a.mp3", title="One").read_bytes())
    song_id = all_songs(app)[0].id
    token = csrf_token(logged_in, f"/library/{song_id}/edit")
    base = {"title": "One", "artist": "", "tags": "", "start": "", "end": "", "csrf_token": token}
    logged_in.post(f"/library/{song_id}/edit", data=base, follow_redirects=False)  # box left unticked
    assert all_songs(app)[0].auto_fill is False
    assert 'name="auto_fill"' in logged_in.get(f"/library/{song_id}/edit").text
    logged_in.post(f"/library/{song_id}/edit", data={**base, "auto_fill": "on"}, follow_redirects=False)
    assert all_songs(app)[0].auto_fill is True


def test_songs_default_to_auto_fill(app, logged_in, tmp_path):
    upload(logged_in, "a.mp3", make_mp3(tmp_path / "a.mp3").read_bytes())
    assert all_songs(app)[0].auto_fill is True


def make_game(app, host, tmp_path):
    return game_id_from(create_game(host, seed_songs(app, host, tmp_path, 12), grid_size=3, tickets=4))


def test_the_old_ticket_addresses_still_work_by_redirecting(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    one = logged_in.get(f"/games/{game_id}/tickets/2", follow_redirects=False)
    assert one.status_code == 307 and one.headers["location"] == f"/games/{game_id}/cards/2"
    pdf = logged_in.get(f"/games/{game_id}/tickets.pdf?paper=a4&per_page=2", follow_redirects=False)
    assert pdf.status_code == 307 and pdf.headers["location"] == f"/games/{game_id}/cards.pdf?paper=a4&per_page=2"
    assert logged_in.get(pdf.headers["location"]).content.startswith(b"%PDF")  # and the new address works
    assert logged_in.get(one.headers["location"]).status_code == 200


def test_pages_say_cards_not_tickets(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    for path in (f"/games/{game_id}", f"/games/{game_id}/cards/1", "/games", "/games/new", "/branding", f"/games/{game_id}/run"):
        text = logged_in.get(path).text
        visible = re.sub(r"(?s)<script.*?</script>", "", text)
        assert "Card" in visible or "card" in visible, path
        for word in (">Ticket", " ticket ", "Tickets<", "tickets "):
            assert word not in visible.replace("ticket_", "").replace("ticket-", ""), (path, word)


def test_the_console_has_one_queue_box_and_a_separate_played_box(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    page = logged_in.get(f"/games/{game_id}/run").text
    assert 'id="queue-card"' in page and "Now playing and coming up" in page
    assert 'id="played-card"' in page and "<details" not in page.split('id="played-card"')[1].split("</section>")[0]
    assert 'id="now-title"' not in page and 'id="next-title"' not in page  # folded into the queue
