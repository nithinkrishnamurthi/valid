# Add status badges to orders table

The orders table currently shows order status as plain text. Replace it with
color-coded pill badges:

| Status      | Background | Text color |
|-------------|------------|------------|
| pending     | #fef3c7    | #92400e    |
| shipped     | #dbeafe    | #1e40af    |
| delivered   | #d1fae5    | #065f46    |
| cancelled   | #fee2e2    | #991b1b    |

Requirements:
- Badge is a rounded pill (border-radius, horizontal padding)
- Replaces the plain text in the Status column
- Text is capitalized (first letter uppercase)
- Table layout and other columns are unaffected
