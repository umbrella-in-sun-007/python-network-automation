# main.py
import yaml
import argparse
from providers.localstack_provider import LocalStackNetworkManager
from providers.gcp_provider import GCPNetworkManager
from validators.ssh_validator import SSHValidator
from utils.logger import get_logger

logger = get_logger("main")

def load_config(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def provision_localstack(cfg):
    ls_cfg = cfg["localstack"]
    manager = LocalStackNetworkManager(endpoint_url=ls_cfg.get("endpoint_url", "http://localhost:4566"),
                                       region_name=ls_cfg.get("region", "us-east-1"))
    logger.info("Provisioning in LocalStack...")
    result = manager.provision_topology(ls_cfg)
    logger.info(f"LocalStack result: {result}")
    return result

def provision_gcp(cfg):
    g_cfg = cfg["gcp"]
    manager = GCPNetworkManager(project_id=g_cfg["project_id"], region=g_cfg.get("region", "us-central1"))
    logger.info("Provisioning in GCP...")
    result = manager.provision_topology(g_cfg)
    logger.info(f"GCP result: keys = {list(result.keys())}")
    return result

def validate(cfg):
    vcfg = cfg.get("validation", {}).get("ssh", {})
    if not vcfg:
        logger.info("No validation config found.")
        return
    validator = SSHValidator(user=vcfg.get("user"), key_path=vcfg.get("key_path", vcfg.get("key_path", "~/.ssh/id_rsa")))
    hosts = vcfg.get("hosts", [])
    commands = vcfg.get("commands", ["ip route"])
    for host in hosts:
        out = validator.run_commands(host, commands)
        logger.info(out)

def main():
    parser = argparse.ArgumentParser(description="Cloud network sync tool")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--env", choices=["localstack", "gcp", "both"], default="both")
    parser.add_argument("--action", choices=["provision", "validate", "all"], default="all")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.env in ("localstack", "both") and args.action in ("provision", "all"):
        provision_localstack(cfg)
    if args.env in ("gcp", "both") and args.action in ("provision", "all"):
        provision_gcp(cfg)
    if args.action in ("validate", "all"):
        validate(cfg)

if __name__ == "__main__":
    main()
