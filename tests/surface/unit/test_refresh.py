from kyno.sdk import is_direction_block, refresh

BLOCK_V1 = "[kyno:direction constitution=default version=1]\nMission: M1"
BLOCK_V2 = "[kyno:direction constitution=default version=2]\nMission: M2"


def test_given_texts_when_looking_for_blocks_then_only_marker_first_text_counts():
    assert is_direction_block(BLOCK_V1)
    assert not is_direction_block("Mission: M1")
    # Marker text inside other content is data, never the adapter's to delete.
    assert not is_direction_block(f"quoting: {BLOCK_V1}")


def test_given_a_stale_block_when_refreshing_then_the_fresh_one_leads_and_the_old_goes():
    texts = [BLOCK_V1, "role prompt", "task"]
    assert refresh(texts, BLOCK_V2) == [BLOCK_V2, "role prompt", "task"]


def test_given_a_list_without_a_block_when_refreshing_then_it_just_prepends():
    assert refresh(["role prompt"], BLOCK_V1) == [BLOCK_V1, "role prompt"]


def test_given_many_stale_blocks_when_refreshing_then_every_one_is_removed():
    texts = [BLOCK_V1, "task", BLOCK_V1]
    assert refresh(texts, BLOCK_V2) == [BLOCK_V2, "task"]


def test_given_an_item_shape_when_refreshing_then_the_shape_comes_as_parameters():
    # A message-list adapter injects how to read and build its items.
    messages = [
        {"role": "system", "content": BLOCK_V1},
        {"role": "user", "content": "task"},
    ]
    out = refresh(
        messages,
        BLOCK_V2,
        text_of=lambda m: m["content"] if m["role"] == "system" else "",
        make=lambda b: {"role": "system", "content": b},
    )
    assert out == [
        {"role": "system", "content": BLOCK_V2},
        {"role": "user", "content": "task"},
    ]
