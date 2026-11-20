# Ubuntu and EnergyPlus setup adapted from ugr-sail/sinergym at v3.12.2.
FROM ubuntu:24.04@sha256:77eb101c607d6e3d4f5ad0c8a02c2136c689b98aba1f359e6502ba517e5c57ec AS base

ARG TARGETARCH
RUN test "$TARGETARCH" = amd64

# Seed the trust store before the first HTTPS APT request.
ADD --checksum=sha256:641de77d8f142cfd62a1a6f964ba67b20754d3337c480efb529d086075a06c9a https://archive.ubuntu.com/ubuntu/pool/main/c/ca-certificates/ca-certificates_20240203_all.deb /tmp/bootstrap-ca.deb
ARG UBUNTU_SNAPSHOT=20261119T000000Z
RUN dpkg-deb --extract /tmp/bootstrap-ca.deb /tmp/bootstrap-ca \
    && mkdir -p /etc/ssl/certs \
    && cat /tmp/bootstrap-ca/usr/share/ca-certificates/mozilla/*.crt > /etc/ssl/certs/ca-certificates.crt \
    && rm -rf /tmp/bootstrap-ca /tmp/bootstrap-ca.deb \
    && sed -i "s|^URIs: .*|URIs: https://snapshot.ubuntu.com/ubuntu/${UBUNTU_SNAPSHOT}|" /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o APT::Update::Error-Mode=any update \
    && apt-get install -y --no-install-recommends \
        ca-certificates git libexpat1 libgomp1 libx11-6 python3.12 python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

ENV EPLUS_PATH=/usr/local/EnergyPlus-25-1-0 \
    VIRTUAL_ENV=/opt/venv \
    LANG=C.UTF-8
ENV PYTHONPATH="${EPLUS_PATH}" \
    PATH="${EPLUS_PATH}:${VIRTUAL_ENV}/bin:${PATH}"

FROM base AS energyplus
RUN apt-get -o APT::Update::Error-Mode=any update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/energyplus
RUN installer=EnergyPlus-25.1.0-1c11a3d85f-Linux-Ubuntu24.04-x86_64.sh \
    && curl --fail --show-error --silent --location --retry 3 \
        "https://github.com/NatLabRockies/EnergyPlus/releases/download/v25.1.0-WithDSOASpaceListFixes/${installer}" \
        --output "$installer" \
    && printf '%s  %s\n' 0f470d59ffb74368cc12ff861cb20848a0b931a4311b2b0cf22defd47075c492 "$installer" | sha256sum --check \
    && chmod +x "$installer" \
    && printf 'y\n' | "./$installer" \
    && test -x "$EPLUS_PATH/energyplus"

FROM base AS runtime
COPY --from=energyplus /usr/local/EnergyPlus-25-1-0/ /usr/local/EnergyPlus-25-1-0/
COPY requirements-build.lock requirements.lock /tmp/

RUN python3.12 -m venv "$VIRTUAL_ENV" \
    && python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: \
        --require-hashes -r /tmp/requirements-build.lock \
    && python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: \
        --no-binary=tinynumpy --no-build-isolation \
        --require-hashes -r /tmp/requirements.lock \
    && python -m pip check \
    && rm /tmp/requirements-build.lock /tmp/requirements.lock

COPY docker/check_versions.py /opt/ecobuilding/check_versions.py
WORKDIR /workspaces/EcoBuilding-MARL
USER ubuntu
RUN python /opt/ecobuilding/check_versions.py
CMD ["bash"]
