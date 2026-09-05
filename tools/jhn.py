import json, psycopg2, psycopg2.extras
CFG = json.load(open('/home/user/workspace/.secrets/jhn.json'))
def conn():
    return psycopg2.connect(host=CFG['host'], port=CFG['port'], dbname=CFG['dbname'],
                            user=CFG['user'], password=CFG['password'], sslmode='disable',
                            connect_timeout=20)
def q(sql, args=None):
    with conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args) if args else cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]
