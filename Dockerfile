FROM rayproject/ray:latest-gpu

# (Optional) if your image doesn't already have it
# COPY requirements_compiled.txt /home/ray/requirements_compiled.txt

# Upgrade pip & install packages with constraints file
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir \
        tensorflow torch gymnasium jupyterlab notebook \
        -c /home/ray/requirements_compiled.txt

# Setup workspace
RUN mkdir -p /workspace/code && chmod -R a+rwX /workspace
WORKDIR /workspace/code

EXPOSE 8888

CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--allow-root", "--no-browser"]
