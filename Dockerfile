FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel 

# ARG PYTORCH_VERSION=2.4.0
# ARG PYTHON_VERSION=3.9
# ARG CUDA_VERSION=12.1
# ARG MAMBA_VERSION=24.3.0-0
# ARG CUDA_CHANNEL=nvidia
# ARG INSTALL_CHANNEL=pytorch
# Automatically set by buildx
ARG TARGETPLATFORM

ENV PATH=/opt/conda/bin:$PATH

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ccache \
        curl \
        git && \
        rm -rf /var/lib/apt/lists/*

# Install conda
# translating Docker's TARGETPLATFORM into mamba arches
# RUN case ${TARGETPLATFORM} in \
#          "linux/arm64")  MAMBA_ARCH=aarch64  ;; \
#          *)              MAMBA_ARCH=x86_64   ;; \
#     esac && \
#     curl -fsSL -v -o ~/mambaforge.sh -O  "https://github.com/conda-forge/miniforge/releases/download/${MAMBA_VERSION}/Mambaforge-${MAMBA_VERSION}-Linux-${MAMBA_ARCH}.sh"
# RUN chmod +x ~/mambaforge.sh && \
#     bash ~/mambaforge.sh -b -p /opt/conda && \
#     rm ~/mambaforge.sh

# Install pytorch
# On arm64 we exit with an error code
# RUN case ${TARGETPLATFORM} in \
#          "linux/arm64")  exit 1 ;; \
#          *)              /opt/conda/bin/conda update -y conda &&  \
#                          /opt/conda/bin/conda install -c "${INSTALL_CHANNEL}" -c "${CUDA_CHANNEL}" -y "python=${PYTHON_VERSION}" "pytorch=$PYTORCH_VERSION" "pytorch-cuda=$(echo $CUDA_VERSION | cut -d'.' -f 1-2)"  ;; \
#     esac && \
#     /opt/conda/bin/conda clean -ya

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

RUN git clone -b energy_star_dev https://github.com/huggingface/optimum-benchmark.git /optimum-benchmark && cd /optimum-benchmark && pip install -e .

COPY ./check_h100.py /check_h100.py
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
