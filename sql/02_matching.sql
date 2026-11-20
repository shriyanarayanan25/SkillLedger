-- Recursive skill-graph score: for each required skill, walk DOWN the skill graph
-- (Frontend -> React -> ...) and credit freelancers by proficiency / (1 + depth).
CREATE OR REPLACE FUNCTION fn_graph_scores(p_project INT, p_max_depth INT DEFAULT 3)
RETURNS TABLE(user_id INT, graph_score DOUBLE PRECISION) LANGUAGE sql STABLE AS $$
WITH RECURSIVE req AS (SELECT skill_id FROM project_skills WHERE project_id = p_project),
tree(root, skill_id, depth) AS (
  SELECT skill_id, skill_id, 0 FROM req
  UNION ALL
  SELECT t.root, r.child_id, t.depth + 1
  FROM tree t JOIN skill_relations r ON r.parent_id = t.skill_id
  WHERE t.depth < p_max_depth                                   -- also guards against cycles
),
best AS (
  SELECT fs.user_id, t.root, MAX((fs.proficiency / 5.0) / (1 + t.depth)) AS s
  FROM tree t JOIN freelancer_skills fs ON fs.skill_id = t.skill_id
  GROUP BY fs.user_id, t.root
)
SELECT b.user_id, (SUM(b.s) / NULLIF((SELECT COUNT(*) FROM req), 0))::DOUBLE PRECISION
FROM best b GROUP BY b.user_id
$$;

-- 1) Recursive-only ranking
CREATE OR REPLACE FUNCTION fn_match_recursive(p_project INT, p_limit INT DEFAULT 20)
RETURNS TABLE(user_id INT, name TEXT, graph_score DOUBLE PRECISION, semantic_score DOUBLE PRECISION, final_score DOUBLE PRECISION)
LANGUAGE sql STABLE AS $$
SELECT u.user_id, u.name, g.graph_score,
       GREATEST(0, 1 - (u.bio_embedding <=> p.desc_embedding))::DOUBLE PRECISION,
       (0.75 * g.graph_score + 0.10 * (u.rating / 5.0) + 0.10 * (u.available::INT)
        + 0.05 * LEAST(1.0, p.budget / NULLIF(u.hourly_rate * 20, 0)))::DOUBLE PRECISION
FROM (SELECT * FROM fn_graph_scores(p_project) ORDER BY graph_score DESC LIMIT 500) g
JOIN users u ON u.user_id = g.user_id
CROSS JOIN (SELECT * FROM projects WHERE project_id = p_project) p
ORDER BY 5 DESC LIMIT p_limit
$$;

-- 2) Semantic-only ranking (pgvector cosine distance, HNSW index)
CREATE OR REPLACE FUNCTION fn_match_semantic(p_project INT, p_limit INT DEFAULT 20)
RETURNS TABLE(user_id INT, name TEXT, graph_score DOUBLE PRECISION, semantic_score DOUBLE PRECISION, final_score DOUBLE PRECISION)
LANGUAGE sql STABLE AS $$
WITH p AS (SELECT desc_embedding AS emb FROM projects WHERE project_id = p_project),
nn AS (
  SELECT u.user_id, u.name, 1 - (u.bio_embedding <=> (SELECT emb FROM p)) AS sim
  FROM users u WHERE u.role = 'freelancer'
  ORDER BY u.bio_embedding <=> (SELECT emb FROM p) LIMIT p_limit)
SELECT nn.user_id, nn.name, COALESCE(g.graph_score, 0)::DOUBLE PRECISION, nn.sim::DOUBLE PRECISION, nn.sim::DOUBLE PRECISION
FROM nn LEFT JOIN fn_graph_scores(p_project) g ON g.user_id = nn.user_id
ORDER BY nn.sim DESC
$$;

-- 3) Hybrid: candidates from graph UNION vector search, one combined score
CREATE OR REPLACE FUNCTION fn_match_hybrid(
  p_project INT, p_limit INT DEFAULT 20,
  w_graph DOUBLE PRECISION DEFAULT 0.40, w_sem DOUBLE PRECISION DEFAULT 0.40,
  w_rating DOUBLE PRECISION DEFAULT 0.10, w_avail DOUBLE PRECISION DEFAULT 0.05,
  w_budget DOUBLE PRECISION DEFAULT 0.05)
RETURNS TABLE(user_id INT, name TEXT, graph_score DOUBLE PRECISION, semantic_score DOUBLE PRECISION, final_score DOUBLE PRECISION)
LANGUAGE sql STABLE AS $$
WITH proj AS (SELECT desc_embedding AS emb, budget FROM projects WHERE project_id = p_project),
gs AS (SELECT * FROM fn_graph_scores(p_project) ORDER BY graph_score DESC LIMIT 300),
ss AS (SELECT u.user_id FROM users u WHERE u.role = 'freelancer'
       ORDER BY u.bio_embedding <=> (SELECT emb FROM proj) LIMIT 300),
cand AS (SELECT gs.user_id FROM gs UNION SELECT ss.user_id FROM ss),
scored AS (
  SELECT u.user_id, u.name,
         COALESCE(gs.graph_score, 0)::DOUBLE PRECISION AS g,
         GREATEST(0, 1 - (u.bio_embedding <=> proj.emb))::DOUBLE PRECISION AS s,
         (u.rating / 5.0)::DOUBLE PRECISION AS r, (u.available::INT)::DOUBLE PRECISION AS a,
         LEAST(1.0, proj.budget / NULLIF(u.hourly_rate * 20, 0))::DOUBLE PRECISION AS b
  FROM cand c JOIN users u ON u.user_id = c.user_id
  CROSS JOIN proj LEFT JOIN gs ON gs.user_id = c.user_id)
SELECT user_id, name, g, s, w_graph * g + w_sem * s + w_rating * r + w_avail * a + w_budget * COALESCE(b, 0)
FROM scored ORDER BY 5 DESC LIMIT p_limit
$$;
