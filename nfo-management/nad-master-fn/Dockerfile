FROM golang:1.21-alpine AS build
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /nad-master-fn .

FROM scratch
COPY --from=build /nad-master-fn /nad-master-fn
ENTRYPOINT ["/nad-master-fn"]
