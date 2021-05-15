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


def check_save(guid):
    if SAVE_INSTANT:
        saveDatabase(guid)


def joinMember(guid, author, argument, memberID):
    data, roles = check_guild(guid)
    if argument not in roles:
        return "This group does not exist."
    roledata, members = roles[argument]
    if "restricted" in roledata and not author.guild_permissions.manage_roles:
        return
    members.add(memberID)
    check_save(guid)
    print("Joining group", argument, "as user", memberID)
    if author.id == memberID:
        return f"You joined {argument}!"
    else:
        return f"{memberID} joined {argument}" 

@bot.command()
async def join(msg, argument, *args):
    uid = int(args[0]) if len(args) > 0 else msg.author.id
    response = joinMember(msg.guild.id, msg.author, argument, uid)
    if response is not None:
        await msg.send(response)


@bot.command()
async def leave(msg, argument):
    guid = msg.guild.id
    data, roles = check_guild(guid)
    if argument in roles:
        roledata, members = roles[argument]
        if "restricted" in roledata and not msg.author.guild_permissions.manage_roles:
            await msg.send("You cannot edit your membership of this role")
            return
        if msg.author.id in members:
            members.remove(msg.author.id)
            check_save(guid)
            await msg.send(f"You left {argument}")
        else:
            await msg.send(f"You are not in {argument}")
    else:
        await msg.send("This does not exist.")


@bot.command()
async def kick(msg, argument, userID):
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
        check_save(msg.guild.id)
        await msg.send(f"This user was kicked from {argument}")
    else:
        await msg.send(f"This user is not part of {argument}")


@bot.command()
async def ping(msg, argument):
    # Get guild data
    gid = msg.guild.id
    data, roles = check_guild(gid)

    # Check role existance
    if argument not in roles:
        await msg.send("This group does not exist.")
        return

    # Create recentpings entry if none exist
    if gid not in recentpings:
        recentpings[gid] = {}
    recentserverpings = recentpings[gid]
    if argument not in recentserverpings:
        recentserverpings[argument] = 0

    # Check fake role rate limits
    if recentserverpings[argument] + REPINGDELAY > time.time() and not msg.author.guild_permissions.manage_messages:
        return
    recentserverpings[argument] = time.time()

    # Check server rate limit
    if "fastping" in data:
        authorRoleIDS = [role.id for role in msg.author.roles]
        if "global" not in recentserverpings:
            recentserverpings["global"] = 0
        print(data["fastping"].intersection(authorRoleIDS), recentserverpings["global"] + REPINGDELAY, ">", time.time(), recentserverpings["global"] + REPINGDELAY > time.time())
        if (len(data["fastping"].intersection(authorRoleIDS)) == 0) and recentserverpings["global"] + REPINGDELAY > time.time() and not msg.author.guild_permissions.manage_messages:
            await msg.send("Please wait before sending another ping")
            return
        recentserverpings["global"] = time.time()
    
    if "restrictping" in data:
        authorRoleIDS = [role.id for role in msg.author.roles]
        if (len(data["restrictping"].intersection(authorRoleIDS)) == 0) and not msg.author.guild_permissions.manage_messages:
            await msg.send("You do not have permissions to ping")
            return

    # Ping users
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
async def rename(msg, oldname, newname):
    data, roles = check_guild(msg.guild.id)
    if not msg.author.guild_permissions.manage_roles:
        await msg.send("You do not have permission to do this")
        return
    if newname in roles:
        await msg.send("This role already exists, ignoring command.")
        return
    if oldname not in roles:
        await msg.send("This role does not exist, ignoring command.")
        return

    role = roles.pop(oldname)
    roles[newname] = role
    check_save(msg.guild.id)
    await msg.send(f"You renamed {oldname} to {newname}")


@bot.command()
async def configure(msg, argument, *args):
    guid = msg.guild.id
    data, roles = check_guild(guid)
    if not msg.author.guild_permissions.manage_roles:
        await msg.send("You do not have permission to do this")
        return
    message = ""

    if argument == "printdata":
        print(data)
        message = "See console"
    elif argument == "printroles":
        print(roles)
        message = "See console"

    # Cooldown related configuration:
    # -------------------------------
    elif argument == "globalcooldown" or argument == "gcd":
        if args[0] == "enable":
            if "fastping" not in data:
                data["fastping"] = set()
                message += "Enabling global cooldown"
            else:
                message += "Global cooldown was already enabled"

        elif args[0] == "excluderoles":
            if "fastping" not in data:
                data["fastping"] = set()
                message += "Global cooldown not yet enabled, enabling global cooldown\n"
            if len(args) == 0:
                message += "No roles were given\n"
            else:
                for role in args[1:]:
                    if not role.isnumeric():
                        message += role + " is not a role ID\n"
                        continue
                    data["fastping"].add(int(role))
                    message += f"role with id {role}, name {msg.guild.get_role(int(role))} succesfully added\n"

        elif args[0] == "getexcluded":
            if "fastping" in data:
                message += "Curent global cooldown ignoring list:\n"
                for role in data["fastping"]:
                    rolename = msg.guild.get_role(role)
                    message += f"{role}: {rolename}\n"
            else:
                message += "Global cooldown is disabled"

        elif args[0] == "disable":
            if "fastping" in data:
                data.pop("fastping")
                message += "Disabling global cooldown"
            else:
                message += "Global cooldown was not enabled"

        elif args[0] == "includeroles":
            message = ""
            if "fastping" not in data:
                data["fastping"] = set()
                message += "Global cooldown not yet enabled, enabling global cooldown\n"
            if len(args) == 0:
                message += "No roles were given\n"
            else:
                for role in args[1:]:
                    if not role.isnumeric():
                        message += role + " is not a role ID\n"
                        continue
                    if int(role) not in data["fastping"]:
                        message += role + " did not ignore the cooldown\n"
                        continue
                    data["fastping"].remove(int(role))
                    message += f"role with id {role}, name {msg.guild.get_role(int(role))} succesfully removed\n"
        else:
            message = "subcommand not recognized"
    # -------------------------------
    # ping restriction configuration:

    elif argument == "pingrestrictions" or argument == "pr":
        if args[0] == "enable":
            if "restrictping" not in data:
                data["restrictping"] = set()
                message += "Enabling ping restriction"
            else:
                message += "Ping restriction was already enabled"

        elif args[0] == "excluderoles":
            if "restrictping" not in data:
                data["restrictping"] = set()
                message += "Ping restriction not yet enabled, enabling ping restriction\n"
            if len(args) == 0:
                message += "No roles were allowed access\n"
            else:
                for role in args[1:]:
                    if not role.isnumeric():
                        message += role + " is not a role ID\n"
                        continue
                    data["restrictping"].add(int(role))
                    message += f"role with id {role}, name {msg.guild.get_role(int(role))} succesfully added\n"

        elif args[0] == "getexcluded":
            if "restrictping" in data:
                message += "Curent list of roles allowed to ping:\n"
                for role in data["restrictping"]:
                    rolename = msg.guild.get_role(role)
                    message += f"{role}: {rolename}\n"
            else:
                message += "Ping restrictions are disabled"

        elif args[0] == "disable":
            if "restrictping" in data:
                data.pop("restrictping")
                message += "Disabling ping restrictions"
            else:
                message += "Ping restrictions were not enabled"

        elif args[0] == "includeroles":
            message = ""
            if "restrictping" not in data:
                data["restrictping"] = set()
                message += "Ping restrictions not yet enabled, enabling ping restrictions\n"
            if len(args) == 0:
                message += "No roles were given\n"
            else:
                for role in args[1:]:
                    if not role.isnumeric():
                        message += role + " is not a role ID\n"
                        continue
                    if int(role) not in data["restrictping"]:
                        message += role + " was not allowed to ping\n"
                        continue
                    data["restrictping"].remove(int(role))
                    message += f"role with id {role}, name {msg.guild.get_role(int(role))} succesfully removed\n"
        else:
            message = "subcommand not recognized"

    # -------------------------------
    else:
        message = "command not recognized"
    check_save(guid)
    if len(message) > 0:
        await msg.send(message)


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
async def help(msg, *args):
    if len(args) == 0:
        message = """**Basic commands:**\njoin x \n - Join group x\nleave x\n - Leave group x\nping x\n - Mention everyone in the group x\nget\n - See your current groups\nlist\n - Show all existing groups"""
        if msg.author.guild_permissions.manage_roles:
            message += """\n**Requires 'Manage roles':**\ncreate x\n - Create a new group named x that anyone can join.\nhelp create\n - See additional options for create.\ndelete x\n - Remove a existing group by name\nkick x ID\n - Remove a member from group x by userID\njoin x ID\n - Add a user to a group by UID\nhelp globalcooldown\n - see cooldown configuration commands\nhelp pingrestrictions\n - see ping restriction configuration commands"""
        await msg.send(message)
    elif args[0] == "globalcooldown" and msg.author.guild_permissions.manage_roles:
        message  = "**Requires 'Manage roles':**\n"
        message += "configure globalcooldown ... | configure gcd ...\n - configure the global cooldown\n"
        message += "enable\n - enables the global cooldown\n"
        message += "disable\n - disable the global cooldown, erasing all cooldown data\n"
        message += "excluderoles IDS\n - disables the global cooldown for the given roles (by id), and enables it globally\n"
        message += "includeroles IDS\n - reenables the global cooldown for the given roles (by id), and enables it globally\n"
        message += "getexcluded\n - see what role ID's currently ignore the global cooldown\n"

        await msg.send(message)
    elif args[0] == "pingrestrictions" and msg.author.guild_permissions.manage_roles:
        message  = "**Requires 'Manage roles':**\n"
        message += "configure pingrestrictions ... | configure pr ...\n - configure the restrictions\n"
        message += "enable\n - enables the restrictions\n"
        message += "disable\n - disable the restrictions, erasing all related data\n"
        message += "excluderoles IDS\n - disables the restrictions for the given roles (by id), and enables it globally\n"
        message += "includeroles IDS\n - reenables the restrictions for the given roles (by id), and enables it globally\n"
        message += "getexcluded\n - see what role ID's currently ignore the restrictions\n"

        await msg.send(message)
    elif args[0] == "create" and msg.author.guild_permissions.manage_roles:
        message  = "**Requires 'Manage roles':**\n"
        message += "create name options\n - Create a role with a name and optional options:\n"
        message += "restricted\n - Make this role require manage roles to assign and deassign members.\n"

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
