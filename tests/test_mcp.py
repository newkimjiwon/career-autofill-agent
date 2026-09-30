import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_both_mcp_servers_initialize_and_share_profile(tmp_path, profile):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, CAREER_DATA_DIR=str(tmp_path / "data"))
    for command in ("career-match-mcp", "career-autofill-mcp"):
        parameters = StdioServerParameters(
            command="uv",
            args=["--directory", str(root), "run", "--no-sync", command],
            env=env,
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert all("submit" not in name for name in names)
                tool = "save_profile" if command == "career-match-mcp" else "update_profile"
                result = await session.call_tool(tool, {"profile": profile.model_dump(mode="json")})
                assert not result.isError
                if command == "career-match-mcp":
                    assert names == {
                        "read_portfolio",
                        "import_source_snapshot",
                        "save_profile",
                        "get_profile",
                        "discover_db_jobs",
                        "import_job_snapshot",
                        "save_jobs",
                        "recommend_jobs",
                    }
                    loaded = await session.call_tool("get_profile", {})
                    assert "test@example.com" in str(loaded)
                else:
                    assert names == {
                        "open_application",
                        "inspect_application",
                        "update_profile",
                        "preview_autofill",
                        "apply_autofill",
                        "preview_from_snapshot",
                        "verify_from_snapshot",
                        "close_browser",
                    }
                    result = await session.call_tool("inspect_application", {})
                    assert result.isError
                    assert "login" in str(result)
    assert (tmp_path / "data" / "profile.json").stat().st_mode & 0o777 == 0o600


async def test_host_browser_mcp_plans_and_verifies_preserved_values(tmp_path, profile):
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(
        command="uv",
        args=["--directory", str(root), "run", "--no-sync", "career-autofill-mcp"],
        env=dict(os.environ, CAREER_DATA_DIR=str(tmp_path / "data")),
    )
    url = "https://dbgroup.recruiter.co.kr/v1/applicant/resume-form/123?step=2"
    fields = [
        {"id": "f0:0", "index": 0, "label": "성명", "kind": "text"},
        {"id": "f0:1", "index": 1, "label": "이메일", "kind": "email", "value": "keep@example.com"},
    ]

    def payload(result):
        assert not result.isError
        return json.loads(next(block.text for block in result.content if block.type == "text"))

    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            payload(
                await session.call_tool(
                    "update_profile", {"profile": profile.model_dump(mode="json")}
                )
            )
            invalid = await session.call_tool(
                "preview_from_snapshot",
                {"url": "https://dbgroup.recruiter.co.kr/login", "fields": fields},
            )
            assert invalid.isError
            invalid = await session.call_tool(
                "preview_from_snapshot",
                {
                    "url": url,
                    "fields": [{"id": "f0:0", "index": 0, "label": "비밀번호", "kind": "password"}],
                },
            )
            assert invalid.isError
            plan = payload(
                await session.call_tool("preview_from_snapshot", {"url": url, "fields": fields})
            )["plan"]
            assert len(plan["actions"]) == 1
            after = [dict(fields[0], value="테스트지원자"), fields[1]]
            changed = [after[0], dict(fields[1], value="unexpected@example.com")]
            failed = payload(
                await session.call_tool(
                    "verify_from_snapshot", {"plan_id": plan["id"], "url": url, "fields": changed}
                )
            )
            assert failed["status"] == "failed"
            assert not failed["preserved_fields_verified"]
            plan = payload(
                await session.call_tool("preview_from_snapshot", {"url": url, "fields": fields})
            )["plan"]
            result = payload(
                await session.call_tool(
                    "verify_from_snapshot", {"plan_id": plan["id"], "url": url, "fields": after}
                )
            )
            assert result["status"] == "applied"
            assert result["preserved_fields_verified"]
            replay = await session.call_tool(
                "verify_from_snapshot", {"plan_id": plan["id"], "url": url, "fields": after}
            )
            assert replay.isError
