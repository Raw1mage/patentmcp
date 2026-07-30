"""``assert_no_project_drift`` — the shell guard that had no automated test.

Flagged twice across the VANS rounds and never claimed by me: both callers
(``webctl.sh``, ``scripts/patentmcp-self-heal.sh``) are shell-only, so the guard
was verified solely by hand-driving its branches. A regression would surface
only when an operator happened to run the verb — which is exactly how the
original 8-day drift stayed invisible: nothing automated was watching.

These drive the real function out of ``scripts/_compose_lib.sh`` via bash,
stubbing ``docker`` on PATH so no container is touched. What is pinned is the
DECISION (allow / refuse) and the diagnosability of the refusal, not docker.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "scripts" / "_compose_lib.sh"


def _run_guard(tmp_path: Path, *, inspect_stdout: str, inspect_rc: int = 0,
               project: str = "patentmcp-testuser") -> subprocess.CompletedProcess:
    """Source the real lib and call the real guard with a stubbed `docker`.

    The stub prints whatever the caller wants ``docker inspect --format`` to
    yield (the owning compose project), so all three branches are reachable
    without a daemon.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "docker"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s' {inspect_stdout!r}\n"
        f"exit {inspect_rc}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    script = f'. "{LIB}"\nPROJECT={project!r}\nassert_no_project_drift\n'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, timeout=30,
        env={"PATH": f"{bindir}:/usr/bin:/bin", "USER": "testuser"},
    )


def test_lib_is_the_single_source_no_private_copies():
    """Both callers must SOURCE the guard, never redefine it.

    Two copies free to diverge is the F1 defect shape this repo just repaired in
    the Python half; re-introducing it in shell would be the same bug wearing a
    different hat.
    """
    assert LIB.is_file(), f"shared lib missing: {LIB}"
    for caller in ("webctl.sh", "scripts/patentmcp-self-heal.sh"):
        text = (REPO / caller).read_text(encoding="utf-8")
        assert "_compose_lib.sh" in text, f"{caller} does not source the shared lib"
        assert "assert_no_project_drift()" not in text, (
            f"{caller} carries a PRIVATE redefinition — two rule-sets will drift")


def test_guard_allows_when_container_is_ours(tmp_path):
    """Matching project -> exit 0, silent. The normal path must not be noisy."""
    r = _run_guard(tmp_path, inspect_stdout="patentmcp-testuser")
    assert r.returncode == 0, f"refused our own container: {r.stderr}"
    assert r.stderr == "", f"allowed but complained: {r.stderr!r}"


def test_guard_allows_when_no_such_container(tmp_path):
    """Nothing to collide with -> exit 0. A fresh host must not be blocked."""
    r = _run_guard(tmp_path, inspect_stdout="", inspect_rc=1)
    assert r.returncode == 0, f"blocked a clean host: {r.stderr}"


def test_guard_refuses_drift_and_names_the_actual_cause(tmp_path):
    """THE regression this exists for.

    `container_name` is global, so a container held by another project makes
    every up/recreate die inside the daemon with a message that never mentions
    compose projects. Refusing is only half the job — the refusal has to name
    the owner and print the repair, or the operator is back to the 8-day hunt.
    """
    r = _run_guard(tmp_path, inspect_stdout="patentmcp")   # the directory-name drift
    assert r.returncode == 1, "drift was WAVED THROUGH — the daemon conflict returns"
    err = r.stderr
    assert "patentmcp" in err and "patentmcp-testuser" in err, (
        f"refusal names neither the owner nor our project: {err!r}")
    assert "docker compose -p" in err, f"no repair instruction offered: {err!r}"
    assert "docker volume ls" in err, (
        "no warning that the abandoned project still holds the sessions volume "
        f"(the token store): {err!r}")


@pytest.mark.parametrize("script", ["webctl.sh", "scripts/patentmcp-self-heal.sh",
                                    "scripts/_compose_lib.sh"])
def test_shell_scripts_parse(script):
    """A syntax error here breaks container lifecycle, not a test."""
    r = subprocess.run(["bash", "-n", str(REPO / script)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"{script} does not parse: {r.stderr}"


def _executable_lines(path: Path) -> list[tuple[int, str]]:
    """Numbered lines with comments and blanks dropped.

    Written after this module's own first version asserted on raw text and
    matched the ``docker compose -p`` inside the usage HEREDOC at line 10 —
    which sits before the guard, so the test failed while the code was correct.
    A test that reads documentation as if it were behavior is precisely the
    false signal this file exists to eliminate.
    """
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append((i, stripped))
    return out


def test_self_heal_calls_the_guard_before_bringing_anything_up():
    """Order matters: guarding AFTER `up` is guarding nothing.

    ``--heal`` drives the same globally-unique container_name webctl does, so it
    is exposed to the identical drift; the guard has to run first or the daemon
    conflict happens anyway.
    """
    lines = _executable_lines(REPO / "scripts" / "patentmcp-self-heal.sh")
    guard_at = next(i for i, s in lines if "assert_no_project_drift" in s)
    up_at = next(i for i, s in lines if "docker compose -p" in s and "up -d" in s)
    assert guard_at < up_at, (
        f"self-heal runs `up` (line {up_at}) BEFORE the drift guard (line {guard_at})")


@pytest.mark.parametrize("verb_line", ["start", "restart"])
def test_webctl_guards_every_mutating_verb(verb_line):
    """Both mutating verbs must be guarded, not just the one that was debugged.

    ``restart`` is where the 8-day symptom appeared ([1/3] built, [2/3] died),
    but ``start`` drives the same ``up`` against the same global container name.
    Guarding only the verb that happened to hurt leaves the twin unprotected.
    """
    lines = _executable_lines(REPO / "webctl.sh")
    body = [s for _, s in lines]
    verb_at = next(i for i, s in enumerate(body) if s.startswith(f"{verb_line})")
                   or s.startswith(f"{verb_line}|"))
    following = body[verb_at:verb_at + 8]
    assert any("assert_no_project_drift" in s for s in following), (
        f"webctl verb {verb_line!r} reaches docker compose without the guard")
