#!/usr/bin/env bash
set -euo pipefail
version=1.16.6
archive="terraform_${version}_linux_amd64.zip"
curl --fail --silent --show-error --location "https://releases.hashicorp.com/terraform/$version/$archive" -o "/tmp/$archive"
curl --fail --silent --show-error --location "https://releases.hashicorp.com/terraform/$version/terraform_${version}_SHA256SUMS" -o /tmp/terraform-checksums
(cd /tmp && grep " $archive$" terraform-checksums | sha256sum -c -)
python3 -c "import zipfile; zipfile.ZipFile('/tmp/$archive').extract('terraform', '/usr/local/bin')"
chmod 0755 /usr/local/bin/terraform
