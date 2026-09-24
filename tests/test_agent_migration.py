import io,json,os,tempfile,unittest
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
from unittest.mock import patch
from migration.agent_import import AgentMigration
from main import _maybe_agent_migration_cli
class MigrationTests(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.base=Path(self.t.name)
    def tearDown(self):self.t.cleanup()
    def test_dry_run_zero_mutation(self):
        src=self.base/"openclaw";src.mkdir();(src/"SOUL.md").write_text("persona");(src/".env").write_text("TOKEN=secret");root=self.base/"aiba";root.mkdir();data=root/"agent_system";plan=AgentMigration(root,data).plan("claw",src,"user-data");self.assertTrue(plan["dry_run"]);self.assertFalse(data.exists());self.assertTrue(any(x["category"]=="secrets" for x in plan["skipped"]))
    def test_apply_no_secrets_or_overwrite(self):
        src=self.base/"hermes";src.mkdir();(src/"SOUL.md").write_text("new");(src/".env").write_text("KEY=x");skills=src/"skills"/"one";skills.mkdir(parents=True);(skills/"SKILL.md").write_text("skill");root=self.base/"aiba";root.mkdir();(root/"SOUL.md").write_text("existing");report=AgentMigration(root,root/"agent_system").apply(AgentMigration(root,root/"agent_system").plan("hermes",src));self.assertEqual((root/"SOUL.md").read_text(),"existing");self.assertTrue(report["conflicts"]);self.assertTrue((root/"skills"/"hermes-imports"/"one"/"SKILL.md").exists());self.assertFalse(any(p.name==".env" for p in root.rglob("*")))
    def test_cli_preview_without_yes(self):
        src=self.base/"oc";src.mkdir();(src/"MEMORY.md").write_text("memory");root=self.base/"aiba";root.mkdir();out=io.StringIO()
        with patch.dict(os.environ,{"AIBA_ROOT":str(root),"AIBA_DATA_DIR":str(root/"agent_system")},clear=False),redirect_stdout(out),redirect_stderr(io.StringIO()):self.assertEqual(_maybe_agent_migration_cli(["claw","migrate","--source",str(src),"--preset","user-data"]),0)
        self.assertTrue(json.loads(out.getvalue())["dry_run"]);self.assertFalse((root/"agent_system").exists())
if __name__=="__main__":unittest.main()
