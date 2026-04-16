CREATE TABLE todos (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    done BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO todos (title) VALUES
    ('Buy groceries'),
    ('Write tests'),
    ('Deploy to production');
