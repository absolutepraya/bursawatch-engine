from pathlib import Path
import subprocess


ENTRYPOINT=Path(__file__).resolve().parents[1]/'bin/bursawatch-dc-morning-brief-job.sh'


def test_command_job_supplies_live_explicitly_without_executing_dispatcher():
    # Replace exec only in this test shell, so no runtime, provider or post runs.
    result=subprocess.run(['bash','-c','job_entrypoint=$1; shift; exec() { printf "%s\\n" "$@"; }; source "$job_entrypoint"',
                           'synthetic-job',str(ENTRYPOINT)],capture_output=True,text=True)
    assert result.returncode==0
    assert result.stdout.splitlines()==[str(Path.home()/'.hermes/scripts/bursawatch-dc-morning-brief-scheduled.sh'),'--live']


def test_job_rejects_manual_arguments_without_starting_runtime():
    result=subprocess.run(['bash',str(ENTRYPOINT),'--check'],capture_output=True,text=True)
    assert result.returncode==2 and not result.stdout
    assert 'accepts no arguments' in result.stderr
