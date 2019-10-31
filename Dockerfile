FROM frolvlad/alpine-miniconda3

RUN mkdir -p /usr/src/app

RUN conda install nomkl && \
    conda install pyproj && \
    apk add git openssh && \
    cd /usr/src && \
    git clone https://github.com/eclipse/paho.mqtt.python && \
    cd paho.mqtt.python && \
    python setup.py install

WORKDIR /usr/src/app

ADD . /usr/src/app

ENTRYPOINT ["/opt/conda/bin/python", "-u", "ntrip2mqtt.py"]
