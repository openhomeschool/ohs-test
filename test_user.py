
from app import db_scaffolding as dbs
t = dbs.Test_Loop()
from app import sql

try:
	t.run(sql.create_user, 'test1', 'pass', 1)
	uuid = t.run(sql.login, 'test1', 'pass')
	assert(uuid != None)
	print(uuid)
	t.run(sql.add_role, 'test1', 'parent')
	t.run(sql.add_roles, 'test1', ('tutor', 'coordinator'))
	assert(t.run(sql.authorized, uuid, ('student', 'tutor', 'admin'))) # neither 'student' nor 'admin' would work, but since 'tutor' is allowed, and this user is a tutor, then this passes
	assert(not t.run(sql.authorized, uuid, ('admin',)))

	t.run(sql.reset_user_password, uuid, 'pass2')
	t.run(sql.forget_login, uuid)

	uuid = t.run(sql.login, 'test1', 'pass2')
	assert(uuid != None)
	t.run(sql.forget_login, uuid)
finally:
	t.run(sql.delete_user, 'test1')

try:
	t.run(sql.create_user, 'mom1', 'pass', 1)
	mom1 = t.run(sql.get_user_id, 'mom1')
	t.run(sql.create_user, 'kid1', 'pass', 1)
	kid1 = t.run(sql.get_user_id, 'kid1')
	t.run(sql.create_user, 'kid2', 'pass', 1)
	kid2 = t.run(sql.get_user_id, 'kid2')
	t.run(sql.create_user, 'kid3', 'pass', 1)
	kid3 = t.run(sql.get_user_id, 'kid3')

	# typical setup - switch from mom to any kids, and between any kids, without password
	t.run(sql.add_user_switch_allows, (kid1, kid2, mom1,), user_id = kid3, without_password = True)
	t.run(sql.add_user_switch_allows, (kid1, mom1, kid3,), user_id = kid2, without_password = True)
	t.run(sql.add_user_switch_allows, (mom1, kid2, kid3,), user_id = kid1, without_password = True)
	t.run(sql.add_user_switch_allows, (kid1, kid2, kid3,), user_id = mom1, without_password = False)

	uuid = t.run(sql.login, 'kid1', 'pass')
	assert(uuid != None)
	uuid = t.run(sql.switch_user, uuid, 'kid2')
	assert(uuid != None)
	uuid = t.run(sql.switch_user, uuid, 'kid3')
	assert(uuid != None)
	uuid = t.run(sql.switch_user, uuid, 'mom1')
	assert(uuid == None)

finally:
	t.run(sql.delete_user, 'mom1')
	t.run(sql.delete_user, 'kid1')
	t.run(sql.delete_user, 'kid2')
	t.run(sql.delete_user, 'kid3')
	t.close()
