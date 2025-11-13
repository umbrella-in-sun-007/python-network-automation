# providers/localstack_provider.py
import boto3
from botocore.exceptions import ClientError
from utils.logger import get_logger

logger = get_logger("localstack-provider")

class LocalStackNetworkManager:
    def __init__(self, endpoint_url="http://localhost:4566", region_name="us-east-1"):
        self.endpoint_url = endpoint_url
        self.region_name = region_name
        self.ec2 = boto3.client(
            "ec2",
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

    def ensure_vpc(self, cidr_block, name=None):
        # Idempotent: try to find by tag Name
        filters = [{"Name": "tag:Name", "Values": [name]}] if name else []
        if filters:
            res = self.ec2.describe_vpcs(Filters=filters)
            vpcs = res.get("Vpcs", [])
            if vpcs:
                vpc_id = vpcs[0]["VpcId"]
                logger.info(f"Found existing VPC {vpc_id} for name {name}")
                return vpc_id

        resp = self.ec2.create_vpc(CidrBlock=cidr_block)
        vpc_id = resp["Vpc"]["VpcId"]
        if name:
            self.ec2.create_tags(Resources=[vpc_id], Tags=[{"Key": "Name", "Value": name}])
        logger.info(f"Created VPC {vpc_id} ({cidr_block})")
        # enable dns hostnames
        self.ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})
        return vpc_id

    def ensure_subnet(self, vpc_id, cidr_block, availability_zone=None, name=None):
        # try to find existing by cidr and vpc
        res = self.ec2.describe_subnets(Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "cidr-block", "Values": [cidr_block]}
        ])
        subnets = res.get("Subnets", [])
        if subnets:
            subnet_id = subnets[0]["SubnetId"]
            logger.info(f"Found existing subnet {subnet_id} ({cidr_block})")
            return subnet_id

        params = {"VpcId": vpc_id, "CidrBlock": cidr_block}
        if availability_zone:
            params["AvailabilityZone"] = availability_zone
        resp = self.ec2.create_subnet(**params)
        subnet_id = resp["Subnet"]["SubnetId"]
        if name:
            self.ec2.create_tags(Resources=[subnet_id], Tags=[{"Key": "Name", "Value": name}])
        logger.info(f"Created subnet {subnet_id} ({cidr_block})")
        return subnet_id

    def ensure_route_table_with_default_route(self, vpc_id, destination_cidr_block="0.0.0.0/0", gateway_id=None, name=None):
        # create route table
        resp = self.ec2.create_route_table(VpcId=vpc_id)
        rtb_id = resp["RouteTable"]["RouteTableId"]
        if name:
            self.ec2.create_tags(Resources=[rtb_id], Tags=[{"Key": "Name", "Value": name}])
        logger.info(f"Created route table {rtb_id} in {vpc_id}")
        # Attempt to create route; LocalStack might accept next hop values; if gateway_id provided, set it
        try:
            if gateway_id:
                self.ec2.create_route(RouteTableId=rtb_id, DestinationCidrBlock=destination_cidr_block, GatewayId=gateway_id)
            else:
                # in LocalStack, to simulate internet route we can create a route to a nat or gateway; use a blackhole or ignore errors
                self.ec2.create_route(RouteTableId=rtb_id, DestinationCidrBlock=destination_cidr_block, GatewayId="local-gw")
            logger.info(f"Added route {destination_cidr_block} -> {gateway_id or 'local-gw'}")
        except ClientError as e:
            logger.warning(f"Could not add route (maybe already exists or unsupported): {e}")
        return rtb_id

    def associate_route_table(self, rtb_id, subnet_id):
        try:
            self.ec2.associate_route_table(RouteTableId=rtb_id, SubnetId=subnet_id)
            logger.info(f"Associated route table {rtb_id} with subnet {subnet_id}")
        except ClientError as e:
            logger.warning(f"Failed to associate route table: {e}")

    # convenience method to provision basic topology
    def provision_topology(self, cfg):
        vpc_cfg = cfg["vpc"]
        vpc_id = self.ensure_vpc(vpc_cfg["cidr_block"], name=vpc_cfg.get("name"))
        subnet_ids = []
        for s in cfg.get("subnets", []):
            sid = self.ensure_subnet(vpc_id, s["cidr"], availability_zone=s.get("az"), name=s.get("name"))
            subnet_ids.append(sid)
        rtb_id = self.ensure_route_table_with_default_route(vpc_id, destination_cidr_block=cfg.get("routes", [{}])[0].get("destination_cidr_block", "0.0.0.0/0"), gateway_id=None, name=f"{vpc_cfg.get('name','rt')}-rt")
        for sid in subnet_ids:
            self.associate_route_table(rtb_id, sid)
        return {"vpc_id": vpc_id, "subnet_ids": subnet_ids, "rtb_id": rtb_id}
