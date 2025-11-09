FROM python:3-slim

# Install shfmt for shell script formatting checks
RUN apt-get update && apt-get install -y curl \
  && curl -sS https://github.com/mvdan/sh/releases/download/v3.7.0/shfmt_v3.7.0_linux_amd64 -o /usr/local/bin/shfmt \
  && chmod +x /usr/local/bin/shfmt \
  && apt-get remove -y curl \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/*

# Setup the user account
RUN addgroup --gid 1000 user \
  && adduser --disabled-password --gecos '' --gid 1000 --uid 1000 user
USER user
WORKDIR /home/user
ENV PATH=/home/user/.local/bin:$PATH

# Copy the requirements file into the image
COPY --chown=user requirements.txt /home/user/dmenu-extended/requirements.txt

# Upgrade pip and install required packages for build
RUN python -m pip install --upgrade pip \
  && pip install --upgrade --no-cache-dir -r dmenu-extended/requirements.txt

# Copy the package into the image
COPY --chown=user . /home/user/dmenu-extended

# Install dmenu-extended into the image
RUN cd /home/user/dmenu-extended \
  && python3 -m build --wheel \
  && pip3 install dist/dmenu_extended-*-py3-none-any.whl --upgrade
