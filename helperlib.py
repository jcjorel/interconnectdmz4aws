
from __future__ import print_function
import re
import pdb
import sys
import time
import json
import ipaddress
import boto3
from crhelper import CfnResource
import logging

_is_local_test = False
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter("[%(levelname)s] %(filename)s:%(lineno)d - %(message)s")
ch.setFormatter(formatter)
logger.addHandler(ch)

# Initialise the helper, all inputs are optional, this example shows the defaults
helper = CfnResource(json_logging=True, log_level='DEBUG', boto_level='CRITICAL', sleep_on_delete=120)

try:
    ## Init code goes here
    pass
except Exception as e:
    helper.init_failure(e)

def pprint(json_obj):
    return json.dumps(json_obj, indent=4, sort_keys=True, default=str)

def parse_metastring(data, metastring, func, keywords, prefix=""):
    for k in keywords:
        data.update({"%s%s" % (prefix, k): keywords[k]})
    for keyword in metastring.split(";"):
        if keyword == "":
            continue
        if "=" not in keyword:
            raise ValueError("Missing '=' sign in keyword/value specification (%s??)!" % keyword)
        k, v = keyword.split("=")
        #if k not in keywords.keys():
        if next(filter(lambda kw: kw == k or re.match(kw, k), keywords), None) is None:
            raise ValueError("Unknown keyword '%s'!!" % k)
        data["%s%s" % (prefix, k)] = v
    func()
    missing_keywords = [ k for k in keywords if data["%s%s" % (prefix, k)] is None ]
    if len(missing_keywords):
        raise ValueError("Missing required keywords '%s' in metastring '%s' !!" % (missing_keywords, metastring))

def EndpointConfig_CreateOrUpdate(data, EndpointSpecifications=None, Region=None, EndpointDNSSpecs=None):
    def process_endpoint_specs():
        # Parse LoadBalancerArnsList parameter
        data["LoadBalancerArnsList"] = []
        if "LoadBalancerArns" in data:
            data["LoadBalancerArnsList"] = [ a for a in data["LoadBalancerArns"].split(",") if a != ""]

        # Create the Security Group list for the LZ endpoint
        data["SecurityGroupIds"] = []
        if "EndpointSecurityGroupIds" in data:
            sg_specs = data["EndpointSecurityGroupIds"]
            sg_ids = []
            for sg_id in sg_specs.split(","):
                if sg_id == "":
                    continue
                if not sg_id.startswith("sg-"):
                    raise ValueError("Security group id '%s' has incorrect format!" % item)
                sg_ids.append(sg_id)
            data["SecurityGroupIds"] = sg_ids

        # Manage LoadBalancerAttributes
        for att in ["LoadBalancer"]:
            data["%sAttributesList" %att] = []
            for k_v in data["%sAttributes" % att].split(","):
                if k_v == "":
                    continue
                if ":" not in k_v:
                    raise ValueError("%sAttribute directive '%s' must contain a ':'!" % (att, k_v))
                k, v = k_v.split(":")
                data["%sAttributesList" % att].append({
                    "Key": k,
                    "Value": v
                })

        # Generate DMZ Endpoint Security group
        data["DMZEndpointSecurityGroupIngressRules"] = []
        for client in data["TrustedDMZClients"].split(","):
            if client == "":
                continue
            sg_spec  = {
                "FromPort": "-1",
                "ToPort": "-1",
                "IpProtocol": "-1"
                }
            if client.startswith("sg-"):
                if ":" in client:
                    sg, ownerid = client.split(":")
                    sg_spec.update({
                        "SourceSecurityGroupOwnerId": ownerid,
                        "SourceSecurityGroupId": sg
                        })
                else:
                    sg_spec.update({
                        "SourceSecurityGroupId": client
                        })
            elif client.startswith("pl-"):
                sg_spec.update({
                    "SourcePrefixListId": client
                    })
            else:
                try:
                    # Ensure that we have a well-formed IP networks
                    client = str(ipaddress.IPv4Network(client))
                    sg_spec.update({
                        "CidrIp": client
                        })
                except:
                    raise ValueError("Failed to interpret '%s' as an IPv4 CIDR network!" % client)
            data["DMZEndpointSecurityGroupIngressRules"].append(sg_spec)

    parse_metastring(data, EndpointSpecifications, process_endpoint_specs, {
        "EndpointSecurityGroupIds": "",
        "TrustedDMZClients" : "",
        "LoadBalancerAttributes": "",
        "LoadBalancerArns": "",
        "LoadBalancerArnsList": "",
        "AcceptanceRequired": False
    })

    def process_dns_specs():
        # Parse LZtoDMZEndpointDNSSpecs
        endpoint_dns_fqdn = data["FQDN"]
        if endpoint_dns_fqdn is not None:
            dns_name_parts = [ p for p in endpoint_dns_fqdn.split(".") if p != ""]
            if len(dns_name_parts) != 0:
                if len(dns_name_parts) == 1:
                    raise ValueError("Endpoint DNS name must be a Fully Qualified name (%s)!" % endpoint_dns_fqdn)
                data["DNS.EndpointHost"] = dns_name_parts[0]
                data["DNS.ZoneName"]     = "%s." % ".".join(dns_name_parts[1:])
                data["DNS.FQDN"]         = "%s." % ".".join(dns_name_parts)

    parse_metastring(data, EndpointDNSSpecs, process_dns_specs, {
        "FQDN": "", 
    })
    return data

def EndpointListenerConfig_CreateOrUpdate(data, EndpointSpecifications=None, EndpointListenerSpecifications=None, 
        HealthCheckProtocol=None, Region=None, EndpointDNSSpecs=None):
    ports = []
    def process_endpoint_listener_specs():
        if data["TargetPort"] == "": data["TargetPort"] = data["ListenerPort"]
        if data["HealthCheckPort"] == "": data["HealthCheckPort"] = data["TargetPort"]

        # Parse Targets
        has_instance_target = False
        has_ip_target       = False
        for target in data["Targets"].split(","):
            s = target.split(":")
            tgt, port = (s[0], s[1] if len(s) > 1 else data["TargetPort"])
            d = {
                "Id": tgt,
                "Port": port
            }
            if tgt.startswith("i-"):
                has_instance_target = True
                data["TargetType"]  = "instance"
            else:
                has_ip_target       = True
                data["TargetType"]  = "ip"
                d["AvailabilityZone"] = "all"
            data["TargetList"].append(d)
        if has_instance_target and has_ip_target:
            raise ValueError("Target list specified '%s' contains both 'IP' and 'Instance' based targets which is forbidden!" % Targets)

        # Manage TargetGroupAttributes keyword
        for att in ["TargetGroup"]:
            data["%sAttributesList" %att] = []
            for k_v in data["%sAttributes" % att].split(","):
                if k_v == "":
                    continue
                if ":" not in k_v:
                    raise ValueError("%sAttribute directive '%s' must contain a ':'!" % (att, k_v))
                k, v = k_v.split(":")
                data["%sAttributesList" % att].append({
                    "Key": k,
                    "Value": v
                })
        
        # Manage Match object:
        data["Matcher"] = { "HttpCode": data["Matcher.HttpCode"] }


    default_port = 80
    parse_metastring(data, EndpointListenerSpecifications, process_endpoint_listener_specs, {
        "Targets": "", 
        "TargetList": [],
        "TargetType" : "ip",
        "TargetProtocol": "TCP",
        "TargetPort": "",
        "ListenerProtocol": "TCP",
        "ListenerPort": default_port,
        "TargetGroupAttributes" : "",
        "HealthCheckIntervalSeconds": "30",
        "HealthCheckPath": "/",
        "HealthCheckPort": "",
        "HealthyThresholdCount": "3",
        "UnhealthyThresholdCount": "3",
        "Matcher.HttpCode": "200",
    })

    return data


def GetLZVpcConfig_CreateOrUpdate(data, StackName=None, LZVpcSpecifications=None, 
        DMZVpcSpecifications=None, DMZVpcSubnetCount=None, 
        Region=None, DMZDNSHostedZoneSpecifications=None):
    def process_vpcspec():
        return

    parse_metastring(data, LZVpcSpecifications, process_vpcspec, {
        "VpcTagValue": None,
    }) 

    response = boto3.client("ec2").describe_vpcs(
            Filters = [{
                "Name": "tag:interconnect-dmz:lz-name",
                "Values": [data["VpcTagValue"]]
                }],
            MaxResults=200
    )
    vpcs = response["Vpcs"]
    if len(vpcs) == 0:
        raise ValueError("Can't find a single VPC with tag 'interconnect-dmz:lz-name' and value '%s'!" % (data["VpcTagValue"]))
    if len(vpcs) > 1:
        raise ValueError("Multiple VPCs found with tag 'interconnect-dmz:lz-name' and value '%s'!" % (data["VpcTagValue"]))
    lz_vpc = vpcs[0]
    data["VpcId"] = lz_vpc["VpcId"]

    response = boto3.client("ec2").describe_subnets(
            Filters = [{
                "Name": "tag:interconnect-dmz:lz-name",
                "Values": [data["VpcTagValue"]]
                }],
            MaxResults=200
    )
    subnets = response["Subnets"]
    # Find LZ subnets that are matching availability zones specified in the DMZ VPC
    sas_data = {}
    GetDMZVpcConfig_CreateOrUpdate(sas_data, StackName=StackName, 
            DMZVpcSpecifications=DMZVpcSpecifications, DMZVpcSubnetCount=DMZVpcSubnetCount,
            Region=Region, DMZDNSHostedZoneSpecifications=DMZDNSHostedZoneSpecifications)
    sas_vpc_subnet_count = int(DMZVpcSubnetCount)
    lz_subnet_ids        = []
    for i in range(0, sas_vpc_subnet_count):
        az        = sas_data["Subnet%d.AZ" % i]
        az_subnet = next(filter(lambda s: s["AvailabilityZone"] == az, subnets), None)
        if az_subnet is None:
            raise ValueError("Can't find a LZ subnet tagged with 'interconnect-dmz:lz-name' and value '%s', matching the Availability Zone '%s'!" %
                    (data["VpcTagValue"], az))
        sas_data["Subnet%d.SubnetId" % i] = az_subnet["SubnetId"]
        lz_subnet_ids.append(az_subnet["SubnetId"])
    data["SubnetIds"] = lz_subnet_ids

def GetDMZVpcConfig_CreateOrUpdate(data, StackName=None, DMZVpcSpecifications=None, DMZVpcSubnetCount=None, 
        Region=None, DMZDNSHostedZoneSpecifications=None):
    def process_vpcspec():
        # VcpCIDR=<CIDR>;Subnets=<az-suffix:CIDR>,<az-suffix:CIDR>...
        if DMZVpcSpecifications is None:
            raise ValueError("Missing DMZVpcSpecifications!!")
        if DMZVpcSubnetCount is None:
            raise ValueError("Missing DMZVpcSubnetCount!!")
        try:
            vpc_subnet_count = int(DMZVpcSubnetCount)
        except Exception as e:
            raise ValueError("DMZVpcSubnetCount=%s : %s" % (DMZVpcSubnetCount, e))

        try:
            vpc_network = ipaddress.IPv4Network(data["VpcCIDR"])
        except Exception as e:
            raise ValueError("Can't decode VPC CIDR '%s' as a valid IPv4 network! : %s" % (data["VpcCIDR"], e))

        # Parse subnets
        i = 0
        for subnet in data["Subnets"].split(","):
            az, cidr = subnet.split(":")
            subnet   = "%s%s" % (Region, az)
            try:
                subnet_network = ipaddress.IPv4Network(cidr)
            except Exception as e:
                raise ValueError("Can't decode CIDR '%s' as an IPv4 network for subnet '%s'! : %s" % (cidr, subnet, e))
            if not subnet_network.subnet_of(vpc_network):
                raise ValueError("Subnet '%s' (%s) is not part of VPC CIDR '%s'!" % (subnet, cidr, data["VpcCIDR"]))
            data["Subnet%d.AZ" % i]   = subnet
            data["Subnet%d.CIDR" % i] = cidr
            i += 1

        if vpc_subnet_count != i:
            raise ValueError("DMZVpcSubnetCount(=%d) and list<DMZVpcSpecifications['Targets']>(=%d) do not have the same size!" % 
                    (vpc_subnet_count, i))
        data["SubnetLogicalNameList"] = ",".join([ "Subnet%d" % i for i in range(0, vpc_subnet_count) ])

    parse_metastring(data, DMZVpcSpecifications, process_vpcspec, {
        "Subnets": None,
        "VpcCIDR": None,
    }) 

    def process_hostedzone():
        return

    parse_metastring(data, DMZDNSHostedZoneSpecifications, process_hostedzone, {
        "ZoneName": None,
        "ResolverSourceCIDR": "0.0.0.0/0"
    }, prefix="DMZHostedZone.") 

    return data

def GetLiveConfig_CreateOrUpdate(data, StackName=None, TimeOut=None, DMZVpcSpecifications=None, DMZVpcSubnetCount=None):
    resolver_ips = []
    def process_vpcspec():
        # Get existing subnets
        # TODO: Should find a way to not use an active wait loop (but failed so far to use DependOns...)
        seconds = time.time()
        while time.time() < seconds + int(TimeOut):
            response = boto3.client("ec2").describe_subnets(
                Filters=[{
                    "Name": "tag:aws:cloudformation:stack-name",
                    "Values": [StackName]
                    }],
                MaxResults=200)
            existing_subnets = response["Subnets"]
            if len(existing_subnets) == int(DMZVpcSubnetCount):
                break
            time.sleep(5)
            logger.info("Waiting for the subnets to come up!")

        if len(existing_subnets) != int(DMZVpcSubnetCount):
            raise ValueError("Timeout while waiting for all subnets to come up!")

        logger.info(existing_subnets)

        try:
            vpc_network = ipaddress.IPv4Network(data["VpcCIDR"])
        except Exception as e:
            raise ValueError("Can't decode VPC CIDR '%s' as a valid IPv4 network! : %s" % (data["VpcCIDR"], e))

        # Parse subnets
        for subnet in data["Subnets"].split(","):
            az, cidr = subnet.split(":")
            try:
                subnet_network = ipaddress.IPv4Network(cidr)
            except Exception as e:
                raise ValueError("Can't decode CIDR '%s' as an IPv4 network for subnet '%s'! : %s" % (cidr, e))

            m = [ s["SubnetId"] for s in existing_subnets if ipaddress.IPv4Network(s["CidrBlock"]).compare_networks(subnet_network) == 0]
            if len(m) == 0:
                raise ValueError("Can't find existing subnet for cidr '%s'!" % cidr)

            subnet_id = m[0]
            # Get the Subnet CIDR base + 4 for Resolver
            resolver_ips.append({
                "Ip": str(list(subnet_network.hosts())[3]),
                "SubnetId": subnet_id
            })

    parse_metastring(data, DMZVpcSpecifications, process_vpcspec, {
        "Subnets": None,
        "VpcCIDR": None,
    }) 
    data["DMZHostedZone.IpAddresses"] = resolver_ips

    return data

def FinalizeEndpointConfig_CreateOrUpdate(data, EndpointDnsEntries=None):
    print(pprint(EndpointDnsEntries))
    regional_dns_name = EndpointDnsEntries[0]
    z, n              = regional_dns_name.split(":")
    data["DNS.HostedZoneId"] = z
    data["DNS.DNSName"]      = n

def call(event, context):
    parameters    = event["ResourceProperties"].copy()
    request_type  = event["RequestType"]
    function_name = "%s_%s" % (parameters["Helper"], request_type)
    match_name    = "%s_.*%s.*" % (parameters["Helper"], request_type)
    if "Helper" not in parameters:
        raise ValueError("Missing 'Helper' resource property!")
    if function_name not in globals():
        function_name = next(filter(lambda f: re.match(match_name, f), globals()), None)
        if function_name is None:
            raise ValueError("Unknown helper function '%s'!" % function_name)
    del parameters["Helper"]
    del parameters["ServiceToken"]
    logger.debug(pprint(parameters))

    logger.info("Calling helper function '%s'(%s)..." % (function_name, parameters))
    function       = globals()[function_name]
    function(helper.Data, **parameters)
    logger.info("Data: %s" % helper.Data)
    print("Data: %s" % pprint(helper.Data))

@helper.create
def create(event, context):
    call(event, context)

@helper.update
def update(event, context):
    call(event, context)

@helper.delete
def delete(event, context):
    return

def handler(event, context):
    helper(event, context)


class ContextMock():
    def __init__(self):
        self.aws_request_id = "12345"

    def get_remaining_time_in_millis(self):
        return 15 * 60 * 1000

    def _send(self, status=None, reason="", send_response=None):
        logger.info("Sending response... (fake)")

if __name__ == '__main__':
    _is_local_test = True
    context = ContextMock()
    helper._send = context._send

    # For test purpose
    event = {
            "RequestType": "Create",
            "StackId": "arn:aws:cloudformation:eu-west-1:111111111111:stack/MyTesStack/9c08b090-0a87-11eb-9f09-021e20b443de",
            "RequestId": "MyRequestId",
            "LogicalResourceId": "MyLogicalResourceId",
            "ResponseURL": "https://somewhere",
            "ResourceProperties" : {
                "ServiceToken": "DummyToken",
                "Helper": "EndpointConfig",
                "EndpointSpecifications": "TrustedDMZClients=10.1.2.3,sg-123456,pl-123456,sg-1234:1234",
                "EndpointDNSSpecs": "FQDN=test.internal"
            }
    }
    handler(event, context)
    event = {
            "RequestType": "Create",
            "StackId": "arn:aws:cloudformation:eu-west-1:111111111111:stack/MyTesStack/9c08b090-0a87-11eb-9f09-021e20b443de",
            "RequestId": "MyRequestId",
            "LogicalResourceId": "MyLogicalResourceId",
            "ResponseURL": "https://somewhere",
            "ResourceProperties" : {
                "ServiceToken": "DummyToken",
                "Helper": "EndpointListenerConfig",
                "EndpointListenerSpecifications": "ListenerPort=77;ListenerProtocol=TCP;TargetProtocol=TCP;Targets=10.0.1.0:80,172.16.1.1,10.0.1.1:444;TargetGroupAttributes=a.b:e,c.d:f",
            }
    }
    handler(event, context)
    event = {
            "RequestType": "Update",
            "StackId": "arn:aws:cloudformation:eu-west-1:111111111111:stack/MyTesStack/9c08b090-0a87-11eb-9f09-021e20b443de",
            "RequestId": "MyRequestId",
            "LogicalResourceId": "MyLogicalResourceId",
            "ResponseURL": "https://somewhere",
            "ResourceProperties" : {
                "ServiceToken": "DummyToken",
                "Helper": "GetDMZVpcConfig",
                "DMZVpcSpecifications": "VpcCIDR=10.234.192.0/27;Subnets=a:10.234.192.0/28,b:10.234.192.16/28",
                "DMZVpcSubnetCount": "2",
                "Region": "eu-west-1",
                "DMZDNSHostedZoneSpecifications": "ZoneName=test.internal",
                "StackName": "MyFirstPartnerDMZ"
            },
    }
    handler(event, context)
    event = {
            "RequestType": "Create",
            "StackId": "arn:aws:cloudformation:eu-west-1:111111111111:stack/MyTesStack/9c08b090-0a87-11eb-9f09-021e20b443de",
            "RequestId": "MyRequestId",
            "LogicalResourceId": "MyLogicalResourceId",
            "ResponseURL": "https://somewhere",
            "ResourceProperties" : {
                "ServiceToken": "DummyToken",
                "Helper": "GetLZVpcConfig",
                "LZVpcSpecifications": "VpcTagValue=MyLZ",
                "DMZVpcSpecifications": "VpcCIDR=10.234.192.0/27;Subnets=a:10.234.192.0/28,b:10.234.192.16/28",
                "DMZVpcSubnetCount": "2",
                "Region": "eu-west-1",
                "DMZDNSHostedZoneSpecifications": "ZoneName=test.internal",
                "StackName": "MyFirstPartnerDMZ"
            },
    }
    handler(event, context)
    event = {
            "RequestType": "Create",
            "StackId": "arn:aws:cloudformation:eu-west-1:111111111111:stack/MyTesStack/9c08b090-0a87-11eb-9f09-021e20b443de",
            "RequestId": "MyRequestId",
            "LogicalResourceId": "MyLogicalResourceId",
            "ResponseURL": "https://somewhere",
            "ResourceProperties" : {
                "ServiceToken": "DummyToken",
                "Helper": "GetLiveConfig",
                "DMZVpcSpecifications": "VpcCIDR=10.234.192.0/27;Subnets=a:10.234.192.0/28,b:10.234.192.16/28",
                "StackName": "MyFirstPartnerDMZ",
                "DMZVpcSubnetCount": "2",
                "TimeOut": 10
            },
    }
    event = {
            "RequestType": "Create",
            "StackId": "arn:aws:cloudformation:eu-west-1:111111111111:stack/MyTesStack/9c08b090-0a87-11eb-9f09-021e20b443de",
            "RequestId": "MyRequestId",
            "LogicalResourceId": "MyLogicalResourceId",
            "ResponseURL": "https://somewhere",
            "ResourceProperties" : {
                "ServiceToken": "DummyToken",
                "Helper": "FinalizeEndpointConfig",
                "EndpointDnsEntries":  ["Z38GZ743OKFT7T:vpce-029a64cb994b9d980-focgfw6a.vpce-svc-02a371f4242da5b04.eu-west-1.vpce.amazonaws.com", 
                    "Z38GZ743OKFT7T:vpce-029a64cb994b9d980-focgfw6a-eu-west-1b.vpce-svc-02a371f4242da5b04.eu-west-1.vpce.amazonaws.com", 
                    "Z38GZ743OKFT7T:vpce-029a64cb994b9d980-focgfw6a-eu-west-1a.vpce-svc-02a371f4242da5b04.eu-west-1.vpce.amazonaws.com" ]
            },
    }
    handler(event, context)
