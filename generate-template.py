#!.venv/bin/python3

import io
import os
import argparse
import glob
import hashlib
import pdb
import boto3
import zipfile
from ruamel.yaml import YAML
import jinja2
from jinja2 import Template

parser = argparse.ArgumentParser(description="AWS PartnerVPN importer")
parser.add_argument('--s3-default-bucketname', help="S3 Bucket name where to push the template and Lambda function", type=str, default="")
parser.add_argument('--s3-default-prefix', help="S3 Path Prefix name where to push the template and Lambda function", type=str, default="")
parser.add_argument('--lz2sas-nlb-count', help="Maximum number of NLB to reference in the LZ VPC", type=int, default=1)
parser.add_argument('--lz2sas-nlb-listener-count', help="Maximum number of NLB listeners to attach to a single SAS NLB", type=int, default=3)
parser.add_argument('--sas2lz-nlb-count', help="Maximum number of NLB to create in the SAS VPC", type=int, default=1)
args = parser.parse_args()
args_dict = {}
for a in args._get_kwargs():
        args_dict[a[0]] = a[1]
s3_prefix =  "/".join([i for i in args.s3_default_prefix.split("/") if i != ""])

# Read and perform Jinja2 transformation
with open("template-jinja2.yaml") as f:
   r = Template(f.read()).render(**args_dict)

# Read the template YAML file and inject some values
yaml = YAML()
yaml.preserve_quotes = True
cf_template = yaml.load(io.StringIO(r))
cf_template["Parameters"]["S3Bucket"]["Default"] = args.s3_default_bucketname
cf_template["Parameters"]["S3Prefix"]["Default"] = "" if len(s3_prefix) == 0 else "%s/" % s3_prefix

# Read default parameters
default_values = yaml.load(io.FileIO("default-parameters.yaml"))
for default in default_values:
    key   = default["ParameterKey"]
    value = default["ParameterValue"]
    parameters = cf_template["Parameters"]
    if key not in parameters:
        continue
    param = parameters[key]
    if "Default" in param:
        param["Default"] = value


# Prepare Lambda ZIP file
lambda_zip_data = io.BytesIO()
with zipfile.ZipFile(lambda_zip_data, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
    for filename in ["helperlib.py"]:
        with open(filename) as f:
            zinfo = zipfile.ZipInfo(filename)
            zinfo.external_attr = 0o777 << 16 
            zip_file.writestr(zinfo, f.read())
    site_package_dir = ".venv/lib/python3.7/"
    for filename in glob.iglob(site_package_dir + '**/*', recursive=True):
        if not os.path.isfile(filename):
            continue
        with open(filename, "rb") as f:
            zinfo = zipfile.ZipInfo(filename[len(site_package_dir):])
            zinfo.external_attr = 0o777 << 16 
            zip_file.writestr(zinfo, f.read())

# Remove all zip file
for filename in glob.iglob("delivery/*.zip"):
    os.unlink(filename)
m = hashlib.sha256()
m.update(lambda_zip_data.getvalue())
with open("delivery/%s.zip" % m.hexdigest(), "wb") as f:
    f.write(lambda_zip_data.getvalue())

# Dump the transformed template
cf_template["Parameters"]["HelperLibHash"]["Default"] = m.hexdigest()
template_to_send_stream = io.StringIO()
yaml.dump(cf_template, template_to_send_stream)
template_to_send = template_to_send_stream.getvalue()
print(template_to_send)
with open("delivery/template.yaml", "w") as f:
    f.write(template_to_send)
