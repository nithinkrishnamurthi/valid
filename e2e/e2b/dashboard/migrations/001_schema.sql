CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(255) NOT NULL,
    product VARCHAR(255) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO orders (customer_name, product, amount, status, created_at) VALUES
    ('Alice Johnson',  'Wireless Headphones',  79.99, 'delivered',  NOW() - INTERVAL '2 days'),
    ('Bob Smith',      'USB-C Hub',            45.00, 'shipped',    NOW() - INTERVAL '1 day'),
    ('Carol White',    'Mechanical Keyboard', 129.99, 'pending',    NOW() - INTERVAL '3 hours'),
    ('David Brown',    'Monitor Stand',        34.50, 'delivered',  NOW() - INTERVAL '5 days'),
    ('Eve Davis',      'Webcam HD',            89.99, 'cancelled',  NOW() - INTERVAL '1 day'),
    ('Frank Miller',   'Mouse Pad XL',         24.99, 'shipped',    NOW() - INTERVAL '12 hours'),
    ('Grace Lee',      'Laptop Sleeve',        39.99, 'pending',    NOW() - INTERVAL '1 hour'),
    ('Henry Wilson',   'Bluetooth Speaker',    59.99, 'delivered',  NOW() - INTERVAL '7 days'),
    ('Iris Chen',      'Phone Stand',          19.99, 'shipped',    NOW() - INTERVAL '2 days'),
    ('Jack Taylor',    'Cable Organizer',      14.99, 'pending',    NOW() - INTERVAL '30 minutes');
