# Migrations

Apply in numeric order with the Supabase SQL editor or the Supabase CLI:

```bash
supabase db push        # if using the Supabase CLI with this folder linked
```

or paste each file into **Supabase Dashboard → SQL Editor → Run**.

| File | Purpose |
|---|---|
| `0001_initial_schema.sql` | Profiles, memories, conversations, messages, documents, chunks, RLS |
| `0002_leads.sql` | Saved leads from the lead finder, RLS |

`database/schema.sql` always reflects the latest full schema. New changes go in a new
`000N_description.sql` file; never edit an applied migration.
