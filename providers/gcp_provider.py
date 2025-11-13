# providers/gcp_provider.py
import google.auth
from googleapiclient import discovery
from utils.logger import get_logger
import time

logger = get_logger("gcp-provider")

class GCPNetworkManager:
    def __init__(self, project_id, region):
        self.project = project_id
        self.region = region
        credentials, _ = google.auth.default()
        self.compute = discovery.build("compute", "v1", credentials=credentials, cache_discovery=False)

    def ensure_network(self, network_name, auto_create_subnetworks=False):
        # check existing
        try:
            network = self.compute.networks().get(project=self.project, network=network_name).execute()
            logger.info(f"Found existing network {network_name}")
            return network
        except Exception:
            pass

        body = {
            "name": network_name,
            "autoCreateSubnetworks": auto_create_subnetworks,
        }
        request = self.compute.networks().insert(project=self.project, body=body)
        resp = request.execute()
        self._wait_global_operation(resp)
        logger.info(f"Created network {network_name}")
        return self.compute.networks().get(project=self.project, network=network_name).execute()

    def ensure_subnetwork(self, subnet):
        # subnet: dict with name, ip_cidr_range, region
        name = subnet["name"]
        region = subnet.get("region", self.region)
        try:
            s = self.compute.subnetworks().get(project=self.project, region=region, subnetwork=name).execute()
            logger.info(f"Found existing subnet {name}")
            return s
        except Exception:
            pass
        body = {
            "name": name,
            "ipCidrRange": subnet["ip_cidr_range"],
            "network": f"projects/{self.project}/global/networks/{subnet.get('network_name')}",
        }
        resp = self.compute.subnetworks().insert(project=self.project, region=region, body=body).execute()
        self._wait_region_operation(resp, region)
        logger.info(f"Created subnet {name} in {region}")
        return self.compute.subnetworks().get(project=self.project, region=region, subnetwork=name).execute()

    def ensure_route(self, route_cfg):
        # route_cfg: {name, destRange, nextHopInstance, nextHopIp, nextHopGateway, nextHopVpnTunnel}
        name = route_cfg["name"]
        try:
            r = self.compute.routes().get(project=self.project, route=name).execute()
            logger.info(f"Found route {name}")
            return r
        except Exception:
            pass
        body = {"name": name, "destRange": route_cfg["destRange"]}
        # support nextHopInternet shorthand
        if route_cfg.get("nextHopInternet"):
            body["nextHopGateway"] = f"projects/{self.project}/global/gateways/default-internet-gateway"
        elif route_cfg.get("nextHopIp"):
            body["nextHopIp"] = route_cfg["nextHopIp"]
        elif route_cfg.get("nextHopInstance"):
            body["nextHopInstance"] = route_cfg["nextHopInstance"]
        resp = self.compute.routes().insert(project=self.project, body=body).execute()
        self._wait_global_operation(resp)
        logger.info(f"Created route {name}")
        return self.compute.routes().get(project=self.project, route=name).execute()

    def _wait_global_operation(self, op):
        name = op.get("name")
        while True:
            result = self.compute.globalOperations().get(project=self.project, operation=name).execute()
            if result.get("status") == "DONE":
                if "error" in result:
                    logger.error(f"Operation error: {result['error']}")
                return result
            time.sleep(1)

    def _wait_region_operation(self, op, region):
        name = op.get("name")
        while True:
            result = self.compute.regionOperations().get(project=self.project, region=region, operation=name).execute()
            if result.get("status") == "DONE":
                if "error" in result:
                    logger.error(f"Operation error: {result['error']}")
                return result
            time.sleep(1)

    def provision_topology(self, cfg):
        net_cfg = cfg["network"]
        network = self.ensure_network(net_cfg["name"], net_cfg.get("auto_create_subnetworks", False))
        # attach network name to subnets config for construction
        created_subnets = []
        for s in cfg.get("subnets", []):
            s2 = dict(s)
            s2["network_name"] = net_cfg["name"]
            created = self.ensure_subnetwork(s2)
            created_subnets.append(created)
        for r in cfg.get("routes", []):
            # support a boolean nextHopInternet in config
            rcfg = dict(r)
            if rcfg.get("nextHopInternet"):
                rcfg["nextHopInternet"] = True
            self.ensure_route(rcfg)
        return {"network": network, "subnets": created_subnets}
