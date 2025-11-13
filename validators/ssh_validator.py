# validators/ssh_validator.py
import paramiko
from utils.logger import get_logger
import os

logger = get_logger("ssh-validator")

class SSHValidator:
    def __init__(self, user, key_path=None, password=None, timeout=10):
        self.user = user
        self.key_path = os.path.expanduser(key_path) if key_path else None
        self.password = password
        self.timeout = timeout

    def _get_key(self):
        if self.key_path and os.path.exists(self.key_path):
            return paramiko.RSAKey.from_private_key_file(self.key_path)
        return None

    def run_commands(self, host, commands):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        key = self._get_key()
        try:
            ssh.connect(hostname=host, username=self.user, pkey=key, password=self.password, timeout=self.timeout)
        except Exception as e:
            logger.error(f"SSH connection to {host} failed: {e}")
            return {"host": host, "ok": False, "error": str(e)}
        results = []
        for cmd in commands:
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=self.timeout)
            out = stdout.read().decode("utf-8").strip()
            err = stderr.read().decode("utf-8").strip()
            results.append({"command": cmd, "stdout": out, "stderr": err})
            logger.info(f"[{host}] {cmd} -> stdout len {len(out)} stderr len {len(err)}")
        ssh.close()
        return {"host": host, "ok": True, "results": results}
