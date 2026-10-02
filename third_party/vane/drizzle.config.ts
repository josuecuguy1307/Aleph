import path from 'path';

export default {
  dialect: 'sqlite',
  schema: './src/lib/db/schema.ts',
  out: './drizzle',
  dbCredentials: {
    url: path.join(process.cwd(), 'data', 'db.sqlite'),
  },
};
