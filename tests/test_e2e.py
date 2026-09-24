"""End-to-end smoke test: real create_agent + scripted model, no network."""

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from nb_langchain_agentskills.loaders import DirectorySkillLoader
from nb_langchain_agentskills.middleware import SkillsMiddleware


class _ScriptedModel(BaseChatModel):
    _script: list = PrivateAttr(default_factory=list)
    _seen: list = PrivateAttr(default_factory=list)
    _index: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append(list(messages))
        message = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def _block_text(block) -> str:
    if isinstance(block, dict):
        return block.get("text", "")
    return getattr(block, "text", "")


def test_create_agent_end_to_end(skill_tree):
    loader = DirectorySkillLoader(skill_tree)
    middleware = SkillsMiddleware(loader)
    model = _ScriptedModel()
    model._script = [
        AIMessage(content="",
            tool_calls=[
                {"name": "skill__load_skill", "args": {"skill_name": "pdf"}, "id": "call-1", "type": "tool_call"}
            ]
        ),
        AIMessage(content="done"),
    ]

    agent = create_agent(model, middleware=[middleware])
    result = agent.invoke({"messages": [HumanMessage(content="Use the pdf skill.")]})

    tool_outputs = [m for m in result["messages"] if m.type == "tool"]
    assert any("<skill_directory>" in m.content for m in tool_outputs)
    assert any("<skill_instructions>" in m.content for m in tool_outputs)

    seen_system = [m for turn in model._seen for m in turn if isinstance(m, SystemMessage)]
    assert seen_system, "middleware did not inject a system message into the model request"
    injected = "\n".join(_block_text(block) for m in seen_system for block in m.content_blocks)
    assert "<available_skills>" in injected
    assert "pdf" in injected
    assert "xlsx" in injected
