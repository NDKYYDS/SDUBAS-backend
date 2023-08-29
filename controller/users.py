import base64
import datetime
import json
import random
import string
import time
import uuid
from io import BytesIO
import pandas as pd
from captcha.image import ImageCaptcha
from fastapi import APIRouter
from fastapi import File, UploadFile
from fastapi import Request, Header, Depends
from Celery.add_operation import add_operation
from Celery.send_email import send_email
from model.db import session_db, user_information_db
from service.user import UserModel, SessionModel, UserinfoModel, OperationModel, encrypted_password, CaptchaModel
from type.functions import make_parameters, search_son_user, get_email_token, get_user_id
from type.page import page
from type.user import user_info_interface, \
    session_interface, email_interface, password_interface, user_add_interface, admin_user_add_interface, \
    login_interface, \
    captcha_interface, user_interface, reason_interface
from utils.auth_login import auth_login, auth_not_login
from utils.response import user_standard_response, page_response, status_response, makePageResult

users_router = APIRouter()
user_model = UserModel()
session_model = SessionModel()
user_info_model = UserinfoModel()
operation_model = OperationModel()
captcha_model = CaptchaModel()

dtype_mapping = {
    'username': str,
    'password': str,
    'email': str,
    'card_id': str,
    'realname': str,
    'gender': int,
    'enrollment_dt': datetime.date,
    'graduation_dt': datetime.date
}


@users_router.post("/user_add")  # 管理员添加一个用户(未添加权限认证)
@user_standard_response
async def user_add(user_information: admin_user_add_interface, request: Request, session=Depends(auth_login)):
    user = user_add_interface(username=user_information.username, password=user_information.password,
                              email=user_information.email, card_id=user_information.card_id)
    result = await user_unique_verify(user)
    ans = json.loads(result.body)
    if ans['code'] != 0:
        return ans
    user_id = user_model.add_user(user)
    user_info = user_info_interface(user_id=user_id, realname=user_information.realname, gender=user_information.gender,
                                    enrollment_dt=user_information.enrollment_dt,
                                    graduation_dt=user_information.graduation_dt)
    user_info_model.add_userinfo(user_info)
    parameters = await make_parameters(request)
    add_operation.delay(0, user_id, '管理员添加一个用户', parameters, session['user_id'])
    return {'message': '添加成功', 'data': True, 'code': 0}


@users_router.post("/user_add_batch")  # 管理员批量添加用户(未添加权限认证)
@user_standard_response
async def user_add_all(request: Request, file: UploadFile = File(...), session=Depends(auth_login)):
    content = await file.read()
    df = pd.read_excel(content, dtype=dtype_mapping)
    user = []
    user_info = []
    for index, row in df.iterrows():
        temp = row[['username', 'password', 'email', 'card_id']].to_dict()
        user_data = user_add_interface(**temp)
        result = await user_unique_verify(user_data)
        ans = json.loads(result.body)
        if ans['code'] != 0:
            ans['message'] = '第' + str(index + 1) + '位' + ans['message']
            return ans
        user_data.registration_dt = user_data.registration_dt.strftime(
            "%Y-%m-%d %H:%M:%S")
        user_data.password = encrypted_password(user_data.password, user_data.registration_dt)
        user.append(user_data)
        temp = row[['realname', 'gender', 'enrollment_dt', 'graduation_dt']].to_dict()
        user_info_data = user_info_interface(**temp)
        user_info.append(user_info_data)
    user_id_list = user_model.add_all_user(user)
    user_info_model.add_all_user_info(user_info, user_id_list)
    parameters = await make_parameters(request)
    add_operation.delay(0, None, '管理员批量添加用户', parameters, session['user_id'])
    return {'message': '添加成功', 'data': True, 'code': 0}


@users_router.get("/user_view")  # 查看管理员所能操作的所有用户(未添加权限认证)
@page_response
async def user_view(pageNow: int, pageSize: int, request: Request):
    # 判断是否有权限
    # 如果有权限
    Page = page(pageSize=pageSize, pageNow=pageNow)
    user_list = search_son_user(request)
    result = {'rows': None}
    if user_list != []:
        user_data = []
        for user_id in user_list:
            name = user_model.get_name_by_user_id(user_id)
            temp = user_interface(username=name[0], realname=name[1])
            user_data.append(temp)
        result = makePageResult(Page, len(user_list), user_data)
    return {'message': '人员如下', "data": result, "code": 0}


@users_router.delete("/user_delete/{user_id}")  # 管理员删除人员(未添加权限认证)
@user_standard_response
async def user_delete(request: Request, user_id: int, session=Depends(auth_login)):
    # 判断是否有权限
    # 如果有权限
    exist_user = user_model.get_user_status_by_user_id(user_id)
    if exist_user is None:
        return {'message': '没有该用户', 'data': False, 'code': 1}
    id = user_model.delete_user(user_id)
    user_info_model.delete_userinfo(user_id)
    parameters = await make_parameters(request)
    add_operation.delay(0, id, '管理员删除一个用户', parameters, session['user_id'])
    return {'message': '删除成功', 'data': True, 'code': 0}


@users_router.put("/user_ban/{user_id}")  # 管理员封禁人员(未添加权限认证)
@user_standard_response
async def user_ban(request: Request, user_id: int, reason: reason_interface, session=Depends(auth_login)):
    # 判断是否有权限
    # 如果有权限
    exist_user = user_model.get_user_status_by_user_id(user_id)
    if exist_user is None:
        return {'message': '没有该用户', 'data': False, 'code': 1}
    if exist_user[0] == 2:
        return {'message': '账号已注销', 'data': False, 'code': 2}
    elif exist_user[0] == 3:
        return {'message': '账号已被封禁', 'data': False, 'code': 3}
    id = user_model.update_user_status(user_id, 3)
    parameters = await make_parameters(request)
    add_operation.delay(0, id, '封禁用户,原因:' + reason.reason, parameters, session['user_id'])
    return {'message': '封禁成功', 'data': True, 'code': 0}


@users_router.put("/user_relieve/{user_id}")  # 管理员解封人员(未添加权限认证)
@user_standard_response
async def user_relieve(request: Request, user_id: int, reason: reason_interface, session=Depends(auth_login)):
    # 判断是否有权限
    # 如果有权限
    exist_user = user_model.get_user_status_by_user_id(user_id)
    if exist_user is None:
        return {'message': '没有该用户', 'data': False, 'code': 1}
    if exist_user[0] == 2:
        return {'message': '账号已注销', 'data': False, 'code': 2}
    elif exist_user[0] == 0 or exist_user[0] == 1:
        return {'message': '账号已被封禁', 'data': False, 'code': 3}
    id = user_model.update_user_status(user_id, 1)
    parameters = await make_parameters(request)
    add_operation.delay(0, id, '解封用户,原因:' + reason.reason, parameters, session['user_id'])
    return {'message': '解封成功', 'data': True, 'code': 0}


@users_router.post("/unique_verify")  # 注册时验证用户用户名和邮箱的唯一性
@user_standard_response
async def user_unique_verify(reg_data: user_add_interface):
    flag = 0
    if reg_data.username is not None:
        exist_username = user_model.get_user_status_by_username(reg_data.username)
        if exist_username is not None:
            return {'message': '用户名已存在', 'code': 1, 'data': False}
    if reg_data.email is not None:
        exist_email = user_model.get_user_status_by_email(reg_data.email)
        if exist_email is not None:
            return {'message': '邮箱已存在', 'code': 2, 'data': False}
    if reg_data.card_id is not None:
        exist_card_id = user_model.get_user_status_by_card_id(reg_data.card_id)
        if exist_card_id is not None:
            return {'message': '学号已存在', 'code': 3, 'data': False}
    return {'message': '满足条件', 'code': 0, 'data': True}


@users_router.get("/get_captcha")  # 获得图片验证码
@user_standard_response
async def get_captcha():
    characters = string.digits + string.ascii_uppercase  # characters为验证码上的字符集，10个数字加26个大写英文字母
    width, height, n_len, n_class = 170, 80, 4, len(characters)
    generator = ImageCaptcha(width=width, height=height)
    random_str = ''.join([random.choice(characters) for j in range(4)])
    img = generator.generate_image(random_str)
    img_byte = BytesIO()
    img.save(img_byte, format='JPEG')  # format: PNG or JPEG
    binary_content = img_byte.getvalue()  # im对象转为二进制流
    captcha = random_str
    id = captcha_model.add_captcha(captcha)
    img_base64 = base64.b64encode(binary_content).decode('utf-8')
    src = f"data: image/jpeg;base64,{img_base64}"
    return {'data': {'captcha': src, 'captchaId': str(id)}, 'message': '获取成功', 'code': 0}


@users_router.post("/send_captcha")  # 验证图片验证码是否正确并发送邮箱验证码
@user_standard_response
async def send_captcha(captcha_data: captcha_interface, request: Request, user_agent: str = Header(None)):
    value = captcha_model.get_captcha_by_id(int(captcha_data.captchaId))
    if value[0] != captcha_data.captcha:
        return {'message': '验证码输入错误', 'code': 1, 'data': False}
    id = None
    str1 = ''
    token = str(uuid.uuid4().hex)  # 生成token
    email_token = get_email_token()
    if captcha_data.type == 0:  # 用户首次登陆时发邮件
        user_information = user_model.get_user_email_by_username(captcha_data.username)
        if user_information is None:  # 看看有没有这个用户名
            return {'data': False, 'message': '没有该用户', 'code': 1}
        if user_information[1] != captcha_data.email:  # 看看有没有这个邮箱
            return {'data': False, 'message': '邮箱不正确，不是之前绑定的邮箱', 'code': 2}
        id = user_information[0]
        send_email.delay(captcha_data.email, email_token, 0)  # 异步发送邮件
        str1 = '用户首次登陆激活账号并向其发送邮件'
    if captcha_data.type == 1:  # 更改邮箱时发邮件
        id = get_user_id(request)
        old_email = user_model.get_user_by_user_id(int(id))  # 新更改邮箱不能与原邮箱相同
        if old_email.email == captcha_data.email:
            return {'message': '不能与原邮箱相同', 'code': 3, 'data': False}
        send_email.delay(captcha_data.email, email_token, 1)  # 异步发送邮件
        str1 = '用户修改绑定邮箱并向新邮箱发送邮件'
    elif captcha_data.type == 2:  # 找回密码时发邮件
        id = user_model.get_user_id_by_email(captcha_data.email)[0]
        send_email.delay(captcha_data.email, token, 2)  # 异步发送邮件
        str1 = '找回密码时向绑定邮箱发送邮件'
    parameters = await make_parameters(request)
    add_operation.delay(0, id, str1, parameters, id)
    session = session_interface(user_id=int(id), ip=request.client.host,
                                func_type=1,
                                token=token, user_agent=user_agent, token_s6=email_token,
                                use_limit=1, exp_dt=(
                datetime.datetime.now() + datetime.timedelta(minutes=5)))  # 新建一个session
    id = session_model.add_session(session)
    session.exp_dt = time.strptime(session.exp_dt.strftime(
        "%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S")  # 将datetime转化为字符串以便转为json
    user_session = json.dumps(session.model_dump())
    session_db.set(token, user_session, ex=300)  # 缓存有效session(时效5分钟)
    return {'data': True, 'token_header': token, 'message': '验证码已发送，请前往验证！', 'code': 0}


@users_router.put("/activation")  # 用户激活
@user_standard_response
async def user_activation(email_data: email_interface, request: Request, token=Depends(auth_not_login), type: int = 0):
    token = request.cookies.get("TOKEN")
    session = session_db.get(token)  # 从缓存中得到有效session
    user_session = session_model.get_session_by_token(token)  # 根据token获取用户的session
    if user_session is None:
        return {'message': '验证码已过期', 'code': 1, 'data': False}
    if session is not None:  # 在缓存中能找到，说明该session有效
        session = json.loads(session)
        if session['token_s6'] == email_data.token_s6:  # 输入的验证码正确
            session_model.update_session_use(user_session.id, 1)  # 把这个session使用次数设为1
            session_model.delete_session(user_session.id)  # 把这个session设为无效
            session_db.delete(token)
            parameters = await make_parameters(request)
            if type == 0:
                user_model.update_user_status(user_session.user_id, 0)
                add_operation.delay(0, user_session.user_id, '用户激活时输入了正确的邮箱验证码通过验证', parameters, user_session.user_id)
                return {'message': '验证成功', 'data': True, 'token_header': '-1', 'code': 0}
            if type == 1:
                user_model.update_user_email(user_session.user_id, email_data.email)
                add_operation.delay(0, user_session.user_id, '修改邮箱时输入了正确的邮箱验证码通过验证', parameters, user_session.user_id)
                return {'message': '验证成功', 'data': True, 'token_header': '-1', 'code': 0}
        else:
            return {'message': '验证码输入错误', 'code': 2, 'data': False}
    else:  # 缓存中找不到，说明已无效
        session_model.delete_session(user_session.id)
        return {'message': '验证码已过期', 'code': 1, 'data': False}


'''
@users_router.post("/user_bind_information")  # 自己注册的用户绑定个人信息
@user_standard_response
async def user_bind_information(request: Request, user_data: user_info_interface, session=Depends(auth_login)):
    card_data = user_add_interface(card_id=user_data.card_id, type=1)
    await user_unique_verify(card_data)
    user_model.update_user_card_id(session['user_id'], user_data.card_id)  # 更新用户的card_id
    user_data.user_id = session['user_id']
    id = user_info_model.add_userinfo(user_data)  # 在user_info表里添加
    user_information = user_information_db.get(session["token"])
    if user_information is not None:
        user_information_db.delete(session["token"])
    current_path = request.url.path
    add_operation.delay(0, session['user_id'], '用户绑定个人信息', '用户通过输入学号，真实姓名，性别，专业，班级，入学时间与毕业时间进行绑定',
                        session['user_id'], current_path)  # 添加一个绑定个人信息的操作
    return {'message': '绑定成功', 'data': True,'code':0}
'''


@users_router.post("/login")  # 登录
@user_standard_response
async def user_login(log_data: login_interface, request: Request, user_agent: str = Header(None),
                     token=Depends(auth_not_login)):
    user_information = user_model.get_user_by_username(log_data.username)  # 先查看要登录的用户名是否存在
    if user_information is None:  # 用户名不存在
        return {'message': '用户名或密码不正确', 'data': False, 'code': 1}
    else:  # 用户名存在
        new_password = encrypted_password(log_data.password, user_information.registration_dt.strftime(
            "%Y-%m-%d %H:%M:%S"))  # 判定输入的密码是否正确
        if new_password == user_information.password:
            status = user_model.get_user_status_by_username(log_data.username)[0]
            if status == 1:
                return {'message': '账号未激活', 'data': False, 'code': 2}
            elif status == 2:
                return {'message': '账号已注销', 'data': False, 'code': 3}
            elif status == 3:
                return {'message': '账号被封禁', 'data': False, 'code': 4}
            token = str(uuid.uuid4().hex)
            session = session_interface(user_id=int(user_information.id), ip=request.client.host,
                                        func_type=0,
                                        token=token, user_agent=user_agent, exp_dt=(
                        datetime.datetime.now() + datetime.timedelta(days=14)))
            id = session_model.add_session(session)
            session.exp_dt = time.strptime(session.exp_dt.strftime(
                "%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S")  # 将datetime转化为字符串以便转为json
            user_session = json.dumps(session.model_dump())
            session_db.set(token, user_session, ex=1209600)  # 缓存有效session
            parameters = await make_parameters(request)
            add_operation.delay(0, int(user_information.id), '用户登录', parameters, int(user_information.id))
            return {'message': '登陆成功', 'token': token, 'data': True, 'code': 0}
        else:
            return {'message': '用户名或密码不正确', 'data': False, 'code': 1}


@users_router.put("/logout")  # 下线
@user_standard_response
async def user_logout(request: Request, session=Depends(auth_login)):
    token = session['token']
    mes = session_model.delete_session_by_token(token)  # 将session标记为已失效
    session_db.delete(token)  # 在缓存中删除
    parameters = await make_parameters(request)
    add_operation.delay(0, session['user_id'], '用户退出登录', parameters, session['user_id'])
    return {'message': '下线成功', 'data': {'result': mes}, 'token': '-1', 'code': 0}


@users_router.put("/username_update")  # 修改用户名
@user_standard_response
async def user_username_update(request: Request, log_data: login_interface, session=Depends(auth_login)):
    user_data = user_add_interface(username=log_data.username)
    await user_unique_verify(user_data)
    user_id = session['user_id']
    user_model.update_user_username(user_id, log_data.username)  # 更新username
    parameters = await make_parameters(request)
    add_operation.delay(0, user_id, '用户通过输入新用户名进行修改', parameters, user_id)
    user_information = user_information_db.get(session["token"])
    if user_information is not None:
        user_information = json.loads(user_information)
        user_information['username'] = log_data['username']
        user_information_db.set(session["token"], json.dumps(user_information), ex=1209600)  # 缓存有效session
    return {'message': '修改成功', 'data': {'user_id': user_id}, 'code': 0}


@users_router.put("/password_update")  # 更改密码
@user_standard_response
async def user_password_update(request: Request, password: password_interface, session=Depends(auth_login)):
    user_id = session['user_id']
    user = user_model.get_user_by_user_id(user_id)
    user.registration_dt = user.registration_dt.strftime("%Y-%m-%d %H:%M:%S")
    if user.password != encrypted_password(password.old_password, user.registration_dt):  # 原密码输入错误
        return {'message': '密码输入不正确', 'data': False, 'code': 1}
    new_password = encrypted_password(password.new_password, user.registration_dt)
    if user.password == new_password:  # 新密码与旧密码相同
        return {'message': '新密码不能与旧密码相同', 'data': False, 'code': 2}
    id = user_model.update_user_password(user_id, new_password)  # 更新新密码
    parameters = await make_parameters(request)
    add_operation.delay(0, id, '用户通过输入原密码，新密码进行更改密码', parameters, id)
    return {'data': {'user_id': id}, 'message': '修改成功', 'code': 0}


@users_router.post("/email_update")  # 更改邮箱
@user_standard_response
async def user_email_update(email_data: email_interface, request: Request, session=Depends(auth_login)):
    token = request.cookies.get("TOKEN")
    result = await user_activation(email_data, request, token, 1)  # 验证验证码是否输入正确
    ans = json.loads(result.body)
    user_information = user_information_db.get(session["token"])
    if user_information is not None:
        user_information = json.loads(user_information)
        user_information['email'] = email_data.email
        user_information_db.set(session["token"], json.dumps(user_information), ex=1209600)  # 缓存有效session
    return {'data': True, 'message': ans['message'], 'code': 0}


@users_router.post("/get_back_password")  # 找回密码
@user_standard_response
async def user_password_get_back(captcha_data: captcha_interface, request: Request, user_agent: str = Header(None)):
    user_information = user_model.get_user_by_username(captcha_data.username)
    if user_information is None:  # 看看有没有这个用户名
        return {'data': False, 'message': '没有该用户', 'code': 1}
    if user_information.email != captcha_data.email:  # 看看有没有这个邮箱
        return {'data': False, 'message': '邮箱不正确，不是之前绑定的邮箱', 'code': 2}
    result = await send_captcha(captcha_data, request, user_agent)
    ans = json.loads(result.body)
    return {'data': True, 'message': ans['message'], 'code': 0}


@users_router.get("/set_password/{token}")  # 找回密码后用户设置密码
@user_standard_response
async def user_set_password(request: Request, new_password: str, token: str):
    user_id = session_model.get_user_id_by_token(token)  # 查出user_id
    if user_id is None:
        return {'data': False, 'message': '无法找到该页面', 'code': 1}
    user_id = user_id[0]
    user_information = user_model.get_user_by_user_id(user_id)
    new_password = encrypted_password(new_password, user_information.registration_dt.strftime(
        "%Y-%m-%d %H:%M:%S"))
    if user_information.password == new_password:
        return {'data': False, 'message': '新密码不能与原密码相同', 'code': 2}
    user_model.update_user_password(user_id, new_password)  # 设置密码
    parameters = await make_parameters(request)
    add_operation.delay(0, user_id, '用户通过输入新密码进行重设密码', parameters, user_id)
    return {'data': True, 'message': '修改成功', 'code': 0}


@users_router.get("/getProfile")  # 查看用户信息
@user_standard_response
async def user_get_Profile(session=Depends(auth_login)):
    user_information = user_information_db.get(session['token'])  # 缓存中中没有
    if user_information is None:
        user_information = user_model.get_user_information_by_id(session['user_id'])
        data = dict(user_information[0].__dict__)
        data['is_bind'] = 0
        if user_information[1] != None:
            data.update(user_information[1].__dict__)
            data['enrollment_dt'] = time.mktime(time.strptime(data['enrollment_dt'].strftime("%Y-%m-%d"), "%Y-%m-%d"))
            data['graduation_dt'] = time.mktime(time.strptime(data['graduation_dt'].strftime("%Y-%m-%d"), "%Y-%m-%d"))
            data['is_bind'] = 1
        data.pop('_sa_instance_state')
        data['registration_dt'] = time.mktime(
            time.strptime(data['registration_dt'].strftime("%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S"))
        Json = json.dumps(data)
        user_information_db.set(session['token'], Json, ex=1209600)
        return {'data': data, 'message': '结果如下', 'code': 0}
    return {'data': json.loads(user_information), 'message': '结果如下', 'code': 0}


@users_router.get("/status")  # 检查用户登录状态
@status_response
async def user_get_status(request: Request):
    token = request.cookies.get("SESSION")
    login_status = 1
    session = session_db.get(token)
    if session is not None:  # 有效session中有，说明登录了
        login_status = 0
        user_id = json.loads(session)['user_id']  # 从缓存中获取user_id
    else:
        user_id = session_model.get_session_by_token(token).user_id  # 根据session获取user_id
    user_information = user_model.get_user_by_user_id(user_id)  # 查找出用户的信息
    account_status = user_information.status  # 帐号状态
    data = dict()
    realname = user_info_model.get_userinfo_by_user_id(user_id).realname
    data['username'] = user_information.username  # 返回用户的基本信息
    data['realname'] = realname
    data['email'] = user_information.email
    data['card_id'] = user_information.card_id
    return {'message': '结果如下', 'data': data, 'login_status': login_status, 'account_status': account_status, 'code': 0}

'''
@users_router.get("/error")  # 检查用户异常状态原因
@user_standard_response
async def user_get_error(username: str):
    user_id = user_model.get
    reason = operation_model.get_operation_by_service_func(0, user_id, '用户封禁')  # 查看被封禁原因
    username = user_model.get_user_by_user_id(reason.oper_user_id).username  # 看被谁封禁
    return {'message': '用户异常状态原因', 'data': {'封禁原因': reason, '封禁人': username}, 'code': 0}
'''