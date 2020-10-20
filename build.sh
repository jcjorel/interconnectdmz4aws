#!/bin/bash -e

if ! [ -e .venv ]; then
	./update-python-requirements
fi

./generate-template.py #--s3-default-bucket "$DMZ_S3_BUCKET" --s3-default-prefix "$DMZ_S3_PREFIX"

