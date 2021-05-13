print("Opening bot.py")

import pickle, time
from discord.ext import commands

# =============================
# Edit these values to change bot functionality:
REPINGDELAY = 20
SAVE_INSTANT = True
# =============================

database = {}
recentpings = {}

print("Defining bot functions")
bot = commands.Bot(command_prefix="+", help_command=None)


def check_guild(guid):
    global database
    if guid not in database:
        try:
            filename = str(guid) + ".dat"
            with open(filename, "rb") as datafile:
                database[guid] = pickle.load(datafile)
        except OSError:
            print(f"Creating new database for guild with ID {guid}")
            database[guid] = ({}, {})
    return database[guid]


def joinMember(guid, author, argument, memberID):
    data, roles = check_guild(guid)
    if argument not in roles:
        return "This group does not exist."
    roledata, members = roles[argument]
    if "restricted" in roledata and not author.guild_permissions.manage_roles:
        return
    members.add(memberID)
    if SAVE_INSTANT:
        saveDatabase(guid)
    print("Joining group", argument, "as user", memberID)
    return f"You joined {argument}!"


@bot.command()
async def join(msg, argument, *args):
    uid = int(args[0]) if len(args) > 0 else msg.author.id
    response = joinMember(msg.guild.id, msg.author, argument, uid)
    if response is not None:
        await msg.send(response)


@bot.command()
async def leave(msg, argument):
    data, roles = check_guild(msg.guild.id)
    if argument in roles:
        roledata, members = roles[argument]
        if "restricted" in roledata and not msg.author.guild_permissions.manage_roles:
            await msg.send("You cannot edit your membership of this role")
            return
        if msg.author.id in members:
            members.remove(msg.author.id)
            if SAVE_INSTANT:
                saveDatabase(msg.guild.id)
            await msg.send(f"You left {argument}")
        else:
            await msg.send(f"You are not in {argument}")
    else:
        await msg.send("This does not exist.")


@bot.command()
async def kick(msg, userID, argument):
    data, roles = check_guild(msg.guild.id)
    if not msg.author.guild_permissions.manage_roles:
        await msg.send("You do not have permission to do this")
        return
    elif argument not in roles:
        await msg.send("This role not exist.")
        return
    elif not userID.isnumeric():
        await msg.send("Enter a numerical user ID")
        return

    userID = int(userID)
    roledata, members = roles[argument]
    if userID in members:
        members.remove(userID)
        if SAVE_INSTANT:
            saveDatabase(msg.guild.id)
        await msg.send(f"This user was kicked from {argument}")
    else:
        await msg.send(f"This user is not part of {argument}")


@bot.command()
async def ping(msg, argument):
    data, roles = check_guild(msg.guild.id)

    if argument not in roles:
        await msg.send("This group does not exist.")
        return

    gid = msg.guild.id
    if gid not in recentpings:
        recentpings[gid] = {}
    recentserverpings = recentpings[gid]
    if argument not in recentserverpings:
        recentserverpings[argument] = 0
    if recentserverpings[argument] + REPINGDELAY > time.time() and not msg.author.guild_permissions.manage_messages:
        return
    recentserverpings[argument] = time.time()

    roledata, members = roles[argument]
    mstring = ", ".join([f"<@{member}>" for member in members])
    await msg.send(f"Mentioning {argument}: " + mstring)


@bot.command()
async def get(msg):
    data, roles = check_guild(msg.guild.id)
    results = [key for key, (_, members) in roles.items()
               if msg.author.id in members]
    if len(results) > 0:
        await msg.send("You are in the following groups: " +
                       ", ".join(results))
    else:
        await msg.send("You are not in any groups.")


@bot.command()
async def create(msg, argument, *args):
    data, roles = check_guild(msg.guild.id)
    if not msg.author.guild_permissions.manage_roles:
        await msg.send("You do not have permission to do this")
        return
    if argument in roles:
        await msg.send("This role already exists, ignoring command.")
        return

    roledata = {}
    for arg in args:
        if arg == "restricted":
            roledata["restricted"] = True

    roles[argument] = (roledata, set())
    if SAVE_INSTANT:
        saveDatabase(msg.guild.id)
    await msg.send(f"You created the fake role '{argument}'!")


@bot.command()
async def delete(msg, argument):
    data, roles = check_guild(msg.guild.id)
    if not msg.author.guild_permissions.manage_roles:
        await msg.send("You do not have permission to do this")
        return
    elif argument not in roles:
        await msg.send("This role does not exist.")
        return

    roles.pop(argument, None)
    if SAVE_INSTANT:
        saveDatabase(msg.guild.id)
    await msg.send("Deleted fake role")


@bot.command()
async def list(msg):
    data, roles = check_guild(msg.guild.id)
    if len(roles) > 0:
        await msg.send(", ".join(roles.keys()))
    else:
        await msg.send("No fake roles exist for this server.")


@bot.command()
async def shutdown(msg):
    if msg.author.guild_permissions.kick_members:
        print("Shutting down\n--------------------------------------------")
        await bot.close()


def saveDatabase(id):
    print(f"saving database for ID {id}")
    db = check_guild(id)
    pickle.dump(db, open(str(id) + ".dat", "wb"))


@bot.command()
async def save(msg):
    if msg.author.guild_permissions.manage_roles:
        saveDatabase(msg.guild.id)
        await msg.send("Saving server database.")


@bot.command()
async def help(msg):
    message = """join x \n - Join group x\nleave x\n - Leave group x\nping x\n - Mention everyone in the group x\nget\n - See your current groups\nlist\n - Show all existing groups"""
    if msg.author.guild_permissions.manage_roles:
        message += """\n**Requires 'Manage roles':**\ncreate x\n - Create a new group named x that anyone can join. add 'restricted' to make sure only people with 'manage roles' can edit this role.\ndelete x\n - Remove a existing group by name\nkick ID x\n - Remove a member from group x by userID\njoin x [uid]\n - Add a user to a group by UID"""
    await msg.send(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        print("Incorrect command, use '-$help'")
        return
    raise error


def main():
    print("reading token")
    token = None
    with open("token.txt") as tokenFile:
        token = tokenFile.readline()
    if token is not None:
        print("token read succesfully")
    print("starting bot")
    bot.run(token)


if __name__ == "__main__":
    main()
