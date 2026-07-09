#!/bin/bash
#curl -X POST "https://gviel-vitiscan-diagno-api.hf.space/diagno" \
curl -X POST "http://localhost:4000/diagno" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@sain-1000x800_99.4.jpg"
