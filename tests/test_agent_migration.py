from pathlib import Path
import json
from migration.agent_import import AgentMigration
from main import _maybe_agent_migration_cli

def test_dry_run_has_zero_mutation(tmp_path):
    src=tmp_path/"openclaw";src.mkdir();(src/"SOUL.md").write_text("persona");(src/".env").write_text("TOKEN=secret")
    root=tmp_path/"aiba";root.mkdir();data=root/"agent_system"
    m=AgentMigration(root,data);plan=m.plan("claw",src,"user-data")
    assert plan["dry_run"] is True
    assert not data.exists()
    assert all(".env" not in x["source"] for x in plan["items"])
    assert any(x["category"]=="secrets" for x in plan["skipped"])

def test_apply_copies_user_data_but_not_secrets_or_existing_targets(tmp_path):
    src=tmp_path/"hermes";src.mkdir();(src/"SOUL.md").write_text("new");(src/".env").write_text("KEY=x")
    skills=src/"skills"/"one";skills.mkdir(parents=True);(skills/"SKILL.md").write_text("skill")
    root=tmp_path/"aiba";root.mkdir();(root/"SOUL.md").write_text("existing");data=root/"agent_system"
    m=AgentMigration(root,data);report=m.apply(m.plan("hermes",src))
    assert (root/"SOUL.md").read_text()=="existing"
    assert report["conflicts"]
    assert (root/"skills"/"hermes-imports"/"one"/"SKILL.md").exists()
    assert not any(p.name==".env" for p in root.rglob("*"))

def test_cli_defaults_to_preview_without_yes(tmp_path,monkeypatch,capsys):
    src=tmp_path/"oc";src.mkdir();(src/"MEMORY.md").write_text("memory")
    root=tmp_path/"aiba";root.mkdir();monkeypatch.setenv("AIBA_ROOT",str(root));monkeypatch.setenv("AIBA_DATA_DIR",str(root/"agent_system"))
    assert _maybe_agent_migration_cli(["claw","migrate","--source",str(src),"--preset","user-data"])==0
    out=json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert not (root/"agent_system").exists()
