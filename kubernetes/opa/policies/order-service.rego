package orderservice

import input

# Default deny all requests
default allow = false

# Allow GET requests from product-service
allow if {
    input.method == "GET"
    input.source == "product-service"
}

# Allow POST requests with valid order data from product-service
allow if {
    input.method == "POST"
    input.source == "product-service"
    valid_order
}

# Define what constitutes a valid order
valid_order if {
    input.request.product_id
    input.request.quantity > 0
}