#! /usr/bin/env python
# -*- coding: UTF-8 -*-
#

from __future__ import absolute_import, unicode_literals

from datetime import date, timedelta, datetime

from flask import (
    Blueprint, render_template, url_for, request, redirect, abort, flash,
    jsonify
)
from flask_login import current_user, login_required, fresh_login_required

from oclubs.objs import User, Club, Activity, Upload, FormattedText
from oclubs.enums import UserType, ClubType, ActivityTime, ClubJoinMode
from oclubs.shared import (
    special_access_required, download_xlsx, read_xlsx, render_email_template,
    Pagination
)
from oclubs.exceptions import PasswordTooShort, NoRow

userblueprint = Blueprint('userblueprint', __name__)


@userblueprint.route('/quit_club/submit', methods=['POST'])
@fresh_login_required
def quitclub_submit():
    '''Delete connection between user and club in database'''
    club = Club(request.form['clubs'])
    if current_user == club.leader:
        flash('You cannot quit a club you lead.', 'quit')
        return redirect(url_for('clubblueprint.quitclub'))
    try:
        club.remove_member(current_user)
    except NoRow:
        flash('You are not a member of ' + club.name + '.', 'quit')
    else:
        reason = request.form['reason']
        parameters = {'user': current_user, 'club': club, 'reason': reason}
        contents = render_email_template('quitclub', parameters)
        club.leader.email_user('Quit Club - ' + current_user.nickname,
                               contents)
        club.leader.notify_user(current_user.nickname + ' has quit ' +
                                club.name + '.')
        flash('You have successfully quitted ' + club.name + '.', 'quit')
    return redirect(url_for('clubblueprint.quitclub'))


@userblueprint.route('/')
@login_required
def personal():
    '''Student Personal Page'''
    pictures = [Upload(-num) for num in range(1, 21)]
    if current_user.type == UserType.STUDENT:
        clubs = current_user.clubs
        castotal = sum(current_user.cas_in_club(club)
                       for club in current_user.clubs)
        meetings_obj = current_user.activities_reminder(
            [ActivityTime.NOON, ActivityTime.AFTERSCHOOL])
        meetings = []
        meetings.extend([meeting for meeting in meetings_obj])
        acts_obj = current_user.activities_reminder([ActivityTime.UNKNOWN,
                                                     ActivityTime.HONGMEI,
                                                     ActivityTime.OTHERS])
        activities = []
        activities.extend([act for act in acts_obj])
        leader_club = filter(lambda club_obj: current_user == club_obj.leader,
                             clubs)
        return render_template('user/student.html',
                               pictures=pictures,
                               clubs=clubs,
                               castotal=castotal,
                               meetings=meetings,
                               activities=activities,
                               leader_club=leader_club)
    elif current_user.type == UserType.TEACHER:
        myclubs = Club.get_clubs_special_access(current_user)
        return render_template('user/teacher.html',
                               pictures=pictures,
                               myclubs=myclubs,
                               UserType=UserType)
    else:
        years = [(date.today() + timedelta(days=365*diff)).year
                 for diff in range(2)]
        return render_template('user/admin.html',
                               pictures=pictures,
                               years=years)


@userblueprint.route('/submit_info', methods=['POST'])
@login_required
def personalsubmitinfo():
    '''Change user's information in database'''
    if request.form['name']:
        current_user.nickname = request.form['name']
    current_user.email = request.form['email']
    phone = request.form['phone']
    current_user.phone = None if phone == 'None' else phone
    if request.form['picture'] is not None:
        pic = int(request.form['picture'])
        if -pic in range(1, 21):
            current_user.picture = Upload(pic)
    flash('Your information has been successfully changed.', 'status_info')
    return redirect(url_for('.personal'))


@userblueprint.route('/submit_password', methods=['POST'])
@login_required
def personalsubmitpassword():
    '''Change user's password in database'''
    user_login = User.attempt_login(current_user.studentid,
                                    request.form['old'])
    if user_login is None:
        flash('You have entered wrong old password. Please enter again.',
              'status_pw')
    elif request.form['new'] == '':
        flash('Please enter new password.', 'status_pw')
    elif request.form['new'] != request.form['again']:
        flash('You have entered two different passwords. '
              'Please enter again.', 'status_pw')
    else:
        try:
            current_user.password = request.form['new']
            flash('Your information has been successfully changed.',
                  'status_pw')
        except PasswordTooShort:
            flash('Password must be at least six digits.', 'status_pw')
    return redirect(url_for('.personal'))


@userblueprint.route('/all_users_info')
@special_access_required
@fresh_login_required
def allusersinfo():
    '''Allow admin to download all users' info'''
    info = []
    info.append(('ID', 'Student ID', 'Nick Name', 'Passport Name', 'Email',
                 'Phone'))
    info.extend([(user.id, user.studentid, user.nickname, user.passportname,
                  user.email, str(user.phone)) for user in User.allusers()])

    return download_xlsx('All Users\' Info.xlsx', info)


@userblueprint.route('/new_teachers')
@special_access_required
@fresh_login_required
def newteachers():
    '''Allow admin to create new user or clubs'''
    return render_template('user/newteachers.html')


@userblueprint.route('/new_teachers/submit', methods=['POST'])
@special_access_required
@fresh_login_required
def newteachers_submit():
    '''Create new teacher accounts with xlsx'''
    if request.files['excel'].filename == '':
        flash('Please upload an excel file.', 'newteachers')
        return redirect(url_for('.newteachers'))
    try:
        contents = read_xlsx(request.files['excel'], 'Teachers',
                             ['ID', 'Official Name', 'Email Address'])
    except KeyError:
        flash('Please change sheet name to "Teachers"', 'newteachers')
        return redirect(url_for('.newteachers'))
    except ValueError:
        flash('Please input in the correct order.', 'newteachers')
        return redirect(url_for('.newteachers'))
    # except BadZipfile:
    #     flash('Please upload an excel file.', 'newteachers')
    #     return redirect(url_for('.newteachers'))

    from oclubs.worker import handle_teacher_xlsx
    for each in contents:
        handle_teacher_xlsx.delay(*each)

    flash('New teacher accounts have been successfully created. '
          'Their passwords have been sent to their accounts.', 'newteachers')
    return redirect(url_for('.newteachers'))


@userblueprint.route('/refresh_users/submit', methods=['POST'])
@special_access_required
@fresh_login_required
def refreshusers_submit():
    '''Upload excel file to create new users'''
    from oclubs.worker import refresh_user
    refresh_user.delay()
    flash('Student accounts\' information has been successfully '
          'scheduled to refresh.', 'refresh_users')
    return redirect(url_for('.personal'))


@userblueprint.route('/rebuild_elastic_search/submit', methods=['POST'])
@special_access_required
@fresh_login_required
def rebuildsearch_submit():
    '''Rebuild elastic search engine to fix asyncronized situation'''
    from oclubs.worker import rebuild_elasticsearch
    rebuild_elasticsearch.delay()
    flash('Search engine has been scheduled to fix.', 'rebuild_search')
    return redirect(url_for('.personal'))


@userblueprint.route('/download_new_passwords')
@special_access_required
@fresh_login_required
def download_new_passwords():
    '''Allow admin to download new accounts' passwords'''
    result = []
    result.append(['Passport Name', 'Login Name', 'Password'])
    users = User.get_new_passwords()
    result.extend([(user.passportname,
                    user.studentid,
                    password) for user, password in users])
    return download_xlsx('New Accounts\' Passwords.xlsx', result)


@userblueprint.route('/disable_accounts')
@special_access_required
@fresh_login_required
def disableaccounts():
    '''Allow admin to disable any account'''
    users = User.allusers()
    return render_template('user/disableaccounts.html',
                           users=users)


@userblueprint.route('/disable_accounts/submit', methods=['POST'])
@special_access_required
@fresh_login_required
def disableaccounts_submit():
    '''Input disabling information into database'''
    user = User(request.form['id'])
    user.password = None
    flash(user.passportname + ' has been successfully disabled.',
          'disableaccounts')
    return redirect(url_for('.disableaccounts'))


@userblueprint.route('/change_password')
@special_access_required
@fresh_login_required
def changepassword():
    '''Allow admin to change users' password'''
    users = User.allusers()
    return render_template('user/changepassword.html',
                           users=users)


@userblueprint.route('/change_password/submit', methods=['POST'])
@special_access_required
@fresh_login_required
def changepassword_submit():
    '''Input new password into database'''
    password = request.form['password']
    if password == '':
        flash('Please input valid password.', 'password')
        return redirect(url_for('.changepassword'))
    user = User(request.form['id'])
    try:
        user.password = password
    except PasswordTooShort:
        flash('Password must be at least six digits.', 'password')
        return redirect(url_for('.changepassword'))
    flash(user.nickname + '\'s password has been successfully set to ' +
          password + '.', 'password')
    return redirect(url_for('.changepassword'))


@userblueprint.route('/forgot_password')
def forgotpw():
    '''Page for retrieving password'''
    return render_template('user/forgotpassword.html')


@userblueprint.route('/change_user_info')
@special_access_required
@fresh_login_required
def changeuserinfo():
    '''Allow admin to change users' information'''
    users = User.allusers()
    return render_template('user/changeuserinfo.html',
                           users=users)


@userblueprint.route('/change_user_info/submit', methods=['POST'])
@special_access_required
@fresh_login_required
def changeuserinfo_submit():
    '''Input change of info into database'''
    property_type = request.form['type']
    content = request.form['content'].strip()
    userid = request.form['userid']
    if content == '-':
        content = None
    else:
        try:
            content = int(content)
        except ValueError:
            pass

    try:
        setattr(User(userid), property_type, content)
    except Exception as e:
        status = type(e).__name__
    else:
        status = 'success'
    return jsonify({'result': status})


@userblueprint.route('/notifications/', defaults={'page': 1})
@userblueprint.route('/notifications/<int:page>')
@login_required
def notifications(page):
    '''Allow users to check their notifications'''
    note_num = 20
    notes_all = current_user.get_notifications(
        limit=((page-1)*note_num, note_num)
    )
    current_user.set_notifications_readall()
    invitations_all = current_user.get_invitation()
    num = current_user.get_unread_notifications_num() + len(invitations_all)
    return render_template('user/notifications.html',
                           notifications=notes_all[1],
                           number=num,
                           pagination=Pagination(page, note_num, notes_all[0]),
                           invitations=invitations_all)


@userblueprint.route('/notifications/submit', methods=['POST'])
@login_required
def invitation_reply():
    reply = request.form['reply']
    club = Club(request.form['club'])

    if not any(inv['club'] == club for inv in current_user.get_invitation()):
        abort(403)
    if reply == "accept":
        club.add_member(current_user)
        flash('You have successfully joined %s.' % club.name, 'reply')
    elif reply == "decline":
        flash('You have declined the invitation of %s.' % club.name, 'reply')
    current_user.delete_invitation(club)
    return redirect(url_for('.notifications'))
