#!/bin/bash -e

DMZ_S3_BUCKET=${1:-$DMZ_S3_BUCKET}
DMZ_S3_PREFIX=${2:-$DMZ_S3_PREFIX}
DMZ_STACK_NAME=${3:-$DMZ_STACK_NAME}
DMZ_PARAMETERS=${4:-example-parameters.yaml}

if [ -z "$DMZ_S3_BUCKET" ] || [ -z "$DMZ_S3_PREFIX" ]; then
	echo "Usage: $0 <s3bucket_where_to_push_the_solution_artificats> <s3prefix> <CF_stack_name> <parameter_YAML_file>" ; exit 1
fi
if [ -z "$DMZ_STACK_NAME" ]; then
	DMZ_STACK_NAME=MyFirstDMZ
fi

if ! which yq &>/dev/null ; then
	echo "Please install 'yq' first! (pip install yq)" ; exit 1
fi

if ! [ -z "$(find . -type f -cnewer delivery/template.yaml 2>/dev/null)" ] ; then
	./build.sh
fi

echo "Pushing artificats to s3://$DMZ_S3_BUCKET/$DMZ_S3_PREFIX..."
aws s3 sync delivery/ s3://$DMZ_S3_BUCKET/$DMZ_S3_PREFIX

parameters=$((
cat ${DMZ_PARAMETERS}
cat <<S3
- ParameterKey:   S3Bucket
  ParameterValue: ${DMZ_S3_BUCKET}
- ParameterKey:   S3Prefix
  ParameterValue: $(echo ${DMZ_S3_PREFIX} | sed s#//*#/#g | sed s#^/##g | sed 's#/$##g' )
S3
) | yq -c .)

if aws cloudformation describe-stacks --stack-name $DMZ_STACK_NAME &>/dev/null
then
	method=update-stack
else
	method=create-stack
fi
OBJECT_KEY=$(echo ${DMZ_S3_PREFIX}/template.yaml | sed s#//*#/#g | sed s#^/##g)
aws cloudformation $method --template-url https://${DMZ_S3_BUCKET}.s3.amazonaws.com/${OBJECT_KEY} \
	--stack-name $DMZ_STACK_NAME \
	--capabilities '["CAPABILITY_NAMED_IAM","CAPABILITY_IAM","CAPABILITY_AUTO_EXPAND"]' \
	--parameter $parameters

