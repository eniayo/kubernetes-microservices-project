package productservice

import input

# Default deny all requests
default allow = false

# Allow GET requests from any service
allow if {
    input.method == "GET"
}

# Allow POST, PUT, DELETE requests only from order-service
allow if {
    input.method in ["POST", "PUT", "DELETE"]
    input.source == "order-service"
}

# Rate limiting: allow if fewer than 100 requests in the last minute
allow if {
    count(input.requests_last_minute) < 100
}