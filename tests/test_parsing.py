import pytest

from nb_langchain_agentskills.exceptions import SkillValidationError
from nb_langchain_agentskills.parsing import metadata_from_frontmatter, parse_skill_md


def test_parse_valid_and_body_hr_preserved():
    frontmatter, body = parse_skill_md("---\nname: a\ndescription: d\n---\n\nBody line\n\n---\n\nafter\n")
    assert frontmatter["name"] == "a"
    assert "---" in body and "after" in body


def test_parse_empty_body_ok():
    frontmatter, body = parse_skill_md("---\nname: a\ndescription: d\n---\n")
    assert body == ""


def test_parse_no_frontmatter():
    with pytest.raises(SkillValidationError):
        parse_skill_md("just text")


def test_parse_unclosed():
    with pytest.raises(SkillValidationError):
        parse_skill_md("---\nname: a\n")


def test_parse_empty_mapping():
    with pytest.raises(SkillValidationError):
        parse_skill_md("---\n---\n")


def test_parse_non_mapping():
    with pytest.raises(SkillValidationError):
        parse_skill_md("---\n- a\n- b\n---\n")


def test_parse_bad_closer():
    with pytest.raises(SkillValidationError):
        parse_skill_md("---\nname: a\n--- oops\nbody")


def test_parse_bom_and_crlf():
    text = "﻿---\r\nname: a\r\ndescription: d\r\n---\r\n\r\nBody\r\n"
    frontmatter, body = parse_skill_md(text)
    assert frontmatter["name"] == "a"
    assert body == "Body"


def test_parse_leading_blank_lines():
    frontmatter, _ = parse_skill_md("\n\n---\nname: a\ndescription: d\n---\nbody")
    assert frontmatter["name"] == "a"


def test_metadata_extra_fields_preserved():
    meta = metadata_from_frontmatter({"name": "a-b", "description": "d", "author": "x"})
    assert meta.name == "a-b"
    assert meta.model_dump()["author"] == "x"


def test_metadata_source_key_in_frontmatter_ignored():
    meta = metadata_from_frontmatter({"name": "a", "description": "d", "source": "github"})
    assert meta.source == "local"


@pytest.mark.parametrize("bad", ["A-b", "-lead", "trail-", "a--b", "a" * 65, "a_b", "a b", ""])
def test_metadata_bad_names(bad):
    with pytest.raises(SkillValidationError):
        metadata_from_frontmatter({"name": bad, "description": "d"})


def test_metadata_bad_description():
    with pytest.raises(SkillValidationError):
        metadata_from_frontmatter({"name": "a", "description": "   "})
    with pytest.raises(SkillValidationError):
        metadata_from_frontmatter({"name": "a", "description": "x" * 1025})
