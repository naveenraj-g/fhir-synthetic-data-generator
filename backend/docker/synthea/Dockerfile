# Synthea runtime image used by the `synthea` connector in docker mode.
# Pinned release (not master-branch-latest, which is a rolling build) so runs are reproducible.
# Build:  docker build -t fhir-gen-synthea:4.0.0 --build-arg SYNTHEA_VERSION=v4.0.0 docker/synthea
FROM eclipse-temurin:17-jre
ARG SYNTHEA_VERSION=v4.0.0
ADD https://github.com/synthetichealth/synthea/releases/download/${SYNTHEA_VERSION}/synthea-with-dependencies.jar /opt/synthea/synthea.jar
LABEL synthea.version="${SYNTHEA_VERSION}"
WORKDIR /opt/synthea
# The connector passes the full JVM command line (-Xmx.. -jar /opt/synthea/synthea.jar ...).
ENTRYPOINT ["java"]
