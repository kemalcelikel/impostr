FROM node:22.17.0-alpine3.22 AS dependencies

WORKDIR /web
COPY package.json package-lock.json .npmrc ./
RUN npm ci

FROM dependencies AS checks
COPY . .
CMD ["npm", "run", "test"]

FROM dependencies AS build
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29.0-alpine AS runtime

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html

EXPOSE 8080
