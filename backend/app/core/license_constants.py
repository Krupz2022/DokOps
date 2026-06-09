# Values injected at Docker build time via ARG + sed — do not edit manually.
# At build: docker build --build-arg LICENSE_SERVER_URL=https://... --build-arg ACTIVATION_ENABLED=true
LICENSE_SERVER_URL: str = "__LICENSE_SERVER_URL__"
ACTIVATION_ENABLED: bool = "__ACTIVATION_ENABLED__" == "true"
