FROM node:22-alpine AS build

WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./

# Build-time legal contacts.  Empty values render an explicit placeholder;
# set them in .env / the deployment environment before a public launch.
ARG LEGAL_CONTACT_EMAIL=""
ARG LEGAL_OWNER_NAME=""
ARG LEGAL_JURISDICTION=""
ENV LEGAL_CONTACT_EMAIL=$LEGAL_CONTACT_EMAIL \
    LEGAL_OWNER_NAME=$LEGAL_OWNER_NAME \
    LEGAL_JURISDICTION=$LEGAL_JURISDICTION

RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
