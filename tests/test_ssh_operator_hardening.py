"""SSH operator hardening (v0.82.8, "SSH Operator Hardening").

v0.82.7 made hammer the canonical git/deploy user but the actual login path
was still root SSH + `sudo -u hammer` for every command - convenient, but it
kept a root session the default habit. This release adds
scripts/setup-board-operator.sh (provisions a trusted public key into
hammer's own authorized_keys, so a *direct* hammer login is possible) and
documents the sshd policy tightened once that was verified live
(`PermitRootLogin prohibit-password`, applied as a drop-in file, never the
distro's own sshd_config).

None of this touches a live sshd or a real second Unix account - these are
the same static, file-text checks the rest of this project's operations
scripts already get in test_deployment_config.py and
test_board_ownership_guard.py.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def _code_lines(text: str) -> str:
    """Non-comment lines only, joined back into one string - so a substring
    check cannot be tripped by a script's own prose explaining what it
    deliberately does *not* do (this file's own scripts do exactly that)."""
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


# --- setup-board-operator.sh: public-key-only, never a private key ----------

def test_setup_board_operator_never_generates_a_keypair():
    text = (SCRIPTS / "setup-board-operator.sh").read_text(encoding="utf-8")
    assert "ssh-keygen" not in _code_lines(text), (
        "setup-board-operator.sh must never generate a keypair itself - "
        "public-key provisioning only (a comment may still tell the operator "
        "to bring their own via ssh-keygen)"
    )


def test_setup_board_operator_refuses_a_private_key_looking_argument():
    text = (SCRIPTS / "setup-board-operator.sh").read_text(encoding="utf-8")
    assert "BEGIN" in text and "refus" in text.lower(), (
        "the script should recognise and refuse a pasted private key rather than writing it verbatim"
    )


def test_setup_board_operator_supports_check_mode():
    text = (SCRIPTS / "setup-board-operator.sh").read_text(encoding="utf-8")
    assert "--check" in text
    assert "CHECK_ONLY" in text


def test_setup_board_operator_is_idempotent_about_the_key_line():
    text = (SCRIPTS / "setup-board-operator.sh").read_text(encoding="utf-8")
    assert "already_present" in text
    assert "grep -qxF" in text, "must compare the exact key line, not a substring match"


def test_setup_board_operator_scopes_permissions_to_the_operator_home():
    text = (SCRIPTS / "setup-board-operator.sh").read_text(encoding="utf-8")
    code = _code_lines(text)
    assert "-m 700" in code or "chmod 700" in code
    assert "chmod 600" in code
    assert "777" not in text


def test_setup_board_operator_never_touches_root_ssh_policy():
    text = (SCRIPTS / "setup-board-operator.sh").read_text(encoding="utf-8")
    code = _code_lines(text)
    for forbidden in ("PermitRootLogin", "PasswordAuthentication", "sshd_config"):
        assert forbidden not in code, (
            f"setup-board-operator.sh's actual code touches {forbidden!r} - key "
            "provisioning and sshd policy must stay two separate, separately-"
            "reviewed steps (a comment may still explain that this is deliberate)"
        )


# --- canonical workflow is documented ----------------------------------------

def test_readme_documents_direct_hammer_ssh_as_canonical():
    text = (REPO_ROOT / "deploy" / "rockpro64" / "README.md").read_text(encoding="utf-8")
    assert "ssh hammer@" in text
    assert "scripts/board-git.sh" in text
    assert "scripts/deploy-production.sh" in text


def test_readme_documents_root_as_emergency_only():
    text = (REPO_ROOT / "deploy" / "rockpro64" / "README.md").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "os/service" in lowered or "emergency" in lowered


def test_readme_documents_the_sshd_policy_and_its_dropin():
    text = (REPO_ROOT / "deploy" / "rockpro64" / "README.md").read_text(encoding="utf-8")
    assert "sshd_config.d" in text
    assert "prohibit-password" in text


# --- board-git.sh and deploy-production.sh still hold their own guards ------
# (regression pins - these were v0.82.7's, re-checked here so a v0.82.8 edit
# cannot silently weaken them while touching nearby operator documentation)

def test_deploy_production_still_refuses_root():
    text = (SCRIPTS / "deploy-production.sh").read_text(encoding="utf-8")
    assert "guard_not_root" in text


def test_board_git_still_delegates_to_the_repo_owner():
    text = (SCRIPTS / "board-git.sh").read_text(encoding="utf-8")
    assert "sudo -u" in text


# --- tracked sshd drop-in reference copy -------------------------------------

def test_sshd_operator_dropin_only_sets_permitrootlogin():
    text = (REPO_ROOT / "deploy" / "rockpro64" / "sshd-operator.conf").read_text(encoding="utf-8")
    code = _code_lines(text)
    assert code.strip() == "PermitRootLogin prohibit-password"


def test_sshd_operator_dropin_never_disables_password_auth_globally():
    """Disabling PasswordAuthentication needs console/local-access recovery
    verified first (not done as of v0.82.8) - the tracked drop-in must not
    quietly grow that directive later without this test being touched too."""
    text = (REPO_ROOT / "deploy" / "rockpro64" / "sshd-operator.conf").read_text(encoding="utf-8")
    assert "PasswordAuthentication" not in _code_lines(text)
