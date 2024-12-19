FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel 

ARG TARGETPLATFORM

ENV PATH=/opt/conda/bin:$PATH

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ccache \
        curl \
        git && \
        rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

RUN git clone -b energy_star_dev https://github.com/huggingface/optimum-benchmark.git /optimum-benchmark && cd /optimum-benchmark && pip install -e .

COPY ./check_h100.py /check_h100.py
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
