# Ticket: Add a toggle endpoint for todos

Add a PATCH endpoint `PATCH /api/todos/:id/toggle` that flips the `done` status
of a todo item. If the todo is currently `done: false`, it should become `done: true`,
and vice versa.

**Requirements:**
- Return the updated todo object
- Return 404 if the todo doesn't exist
- The toggle should be atomic (single UPDATE query)
