from agent.sessions import SessionStore

def test_search_is_user_scoped_and_bounded(tmp_path):
    s=SessionStore(tmp_path/"sessions.db")
    for i in range(40):
        sid=s.open_session("alice",f"project alpha {i}");s.append(sid,summary=f"alpha result {i}")
    sid=s.open_session("bob","project alpha secret");s.append(sid,summary="alpha bob-only")
    rows=s.search("alice","alpha",9999)
    assert len(rows)==25
    assert all(x["user_key"]=="alice" for x in rows)
    assert all("bob-only" not in (x.get("summary") or "") for x in rows)

def test_search_query_is_sanitized_and_empty_query_returns_nothing(tmp_path):
    s=SessionStore(tmp_path/"sessions.db");sid=s.open_session("alice","needle");s.append(sid,summary="needle result")
    assert s.search("alice",'needle" OR *',10)
    assert s.search("alice","***",10)==[]

def test_history_limit_is_bounded(tmp_path):
    s=SessionStore(tmp_path/"sessions.db")
    for i in range(80):s.open_session("alice",str(i))
    assert len(s.list_by_user("alice",100000))==50
