"""flatten_content — shared LangChain content-block flattening helper.

Anthropic extended-thinking and tool-use return AIMessage(Chunk).content as a
list of typed blocks instead of a plain string. Both wire protocols this
runtime speaks (A2A `Message.parts[*].text` and the OpenAI-compatible
`delta`/`text` fields) require a string, so this helper is shared by both.
"""

from _vystak.runtime.content import flatten_content


def test_plain_string_passes_through_unchanged():
    assert flatten_content("hello") == "hello"


def test_list_of_typed_blocks_concatenates_only_text_blocks():
    content = [
        {"type": "thinking", "thinking": "The user wants weather info."},
        {"type": "text", "text": "Sunny"},
        {"type": "tool_use", "id": "t1", "name": "get_weather", "input": {}},
        {"type": "text", "text": " and warm."},
    ]
    assert flatten_content(content) == "Sunny and warm."


def test_list_of_bare_strings_concatenates():
    assert flatten_content(["he", "llo"]) == "hello"


def test_non_str_non_list_falls_back_to_str():
    assert flatten_content(42) == "42"
    assert flatten_content(None) == "None"
