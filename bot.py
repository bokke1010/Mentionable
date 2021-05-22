print("Opening bot.py")

import pickle, time, discord
from discord.ext import commands

# =============================
# Edit these values to change bot functionality:
REPINGDELAY = 20
SAVE_INSTANT = True
# Extra bot functionality besides the original goal:
BOT_EXTRA_ROLELOGS = True
# =============================

intents = discord.Intents.default()
intents.members = True

database = {}
recentpings = {}

print("Defining bot functions")
bot = commands.Bot(command_prefix="+", help_command=None, intents=intents)

def get_name(guild, id):
    user = guild.get_member(id)
    if user is not None:
        nick = user.nick
        if nick is not None:
            return f"{id}: {user.nick} ({user.name})"
        else:
            return f"{id}: {user.name}"
    else:
        return f"unfound user with id {id}"


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


def joinMember(guild, author, argument, memberID):
    data, roles = check_guild(guild.id)
    if argument not in roles:
        return "This group does not exist."
    roledata, members = roles[argument]
    if "restricted" in roledata and not author.guild_permissions.manage_roles:
        return
    if memberID in members:
        if author.id == memberID:
            return f"You were already in the {argument} group"
        else:
            return f"{get_name(guild, memberID)} was already in the {argument} group" 
    members.add(memberID)
    check_save(guild.id)
    print("Joining group", argument, "as user", memberID)
    if author.id == memberID:
        return f"You joined {argument}"
    else:
        return f"{get_name(guild, memberID)} joined {argument}" 

@bot.command()
async def join(msg, argument, *args):
    uids = [int(a) for a in args] if len(args) > 0 and msg.author.guild_permissions.manage_roles else [msg.author.id]
    argument = argument.lower()
    response = ""
    for uid in uids:
        membResponse = joinMember(msg.guild, msg.author, argument, uid) + "\n"
        if len(response) + len(membResponse) > 1980:
            await msg.send(response + "...")
            response = ""
        response += membResponse
    if response is not None:
        await msg.send(response)


@bot.command()
async def leave(msg, argument):
    guid = msg.guild.id
    argument = argument.lower()
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
    guid = msg.guild.id
    argument = argument.lower()
    data, roles = check_guild(guid)
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
    userString = get_name(msg.guild, userID)
    roledata, members = roles[argument]
    if userID in members:
        members.remove(userID)
        check_save(msg.guild.id)
        await msg.send(f"{userString} was kicked from {argument}")
    else:
        await msg.send(f"{userString} is not part of {argument}")


@bot.command()
async def ping(msg, argument):
    # Get guild data
    guid = msg.guild.id
    argument = argument.lower()
    data, roles = check_guild(guid)
    restrictionsApply = not msg.author.guild_permissions.manage_messages

    # Check role existance
    if argument not in roles:
        await msg.send("This group does not exist.")
        return
    roledata, members = roles[argument]

    # Check if the role can be pinged
    if "noping" in roledata and restrictionsApply:
        await msg.send("This role cannot be mentioned normally")
        return

    # Check if user is allowed to ping a role
    if "restrictping" in data and restrictionsApply:
        authorRoleIDS = [role.id for role in msg.author.roles]
        if (len(data["restrictping"].intersection(authorRoleIDS)) == 0):
            await msg.send("You do not have permissions to ping")
            return

    # Get relevant cooldown
    repingdelay = REPINGDELAY
    if "pingdelay" in roledata:
        repingdelay = data["pingdelay"]
    elif "pingdelay" in data:
        repingdelay = data["pingdelay"]

    # Create recentpings entry if none exist
    if guid not in recentpings:
        recentpings[guid] = {}
    recentserverpings = recentpings[guid]
    if argument not in recentserverpings:
        recentserverpings[argument] = 0

    # Check fake role rate limits
    if recentserverpings[argument] + repingdelay > time.time() and restrictionsApply:
        await msg.send("Please wait before sending another ping")
        return
    recentserverpings[argument] = time.time()

    # Check server wide rate limit
    if "fastping" in data:
        if "global" not in recentserverpings:
            recentserverpings["global"] = 0

        authorRoleIDS = [role.id for role in msg.author.roles]
        cooldownApplies = len(data["fastping"].intersection(authorRoleIDS)) == 0
        withinCooldown = recentserverpings["global"] + repingdelay > time.time()
        if cooldownApplies and withinCooldown and restrictionsApply:
            await msg.send("Please wait before sending another ping")
            return
        recentserverpings["global"] = time.time()

    # Ping users
    message = f"Mentioning {argument}: "
    for member in members:
        mstring = f"<@{member}>"
        if len(message) + len(mstring) > 1980:
            await msg.send(message)
            message = ""
        message += mstring + ", "
    await msg.send(message)


@bot.command()
async def get(msg, *args):
    data, roles = check_guild(msg.guild.id)
    if len(args) > 0 and msg.author.guild_permissions.manage_roles:
        if args[0].isnumeric():
            UID = int(args[0])
            results = [key for key, (_, members) in roles.items()
                    if UID in members]
            if len(results) > 0:
                message = get_name(UID) + " is in the following groups: "
                for role in results:
                    if len(message) + len(role) > 1980:
                        await msg.send(message + "...")
                        message = ""
                    message += role + ",   "
                await msg.send(message)
            else:
                await msg.send("This person is not in any groups.")
        elif args[0].lower() in roles:
            roledata, members = roles[args[0].lower()]
            message = f"This group contains the following {len(members)} users:\n"
            for name in (get_name(msg.guild, a) for a in members):
                if len(message) + len(name) > 1980:
                    await msg.send(message + "...")
                    message = ""
                message += name + "\n"
            await msg.send(message)
        else:
            await msg.send("Invalid user ID or role name")
    else:
        results = [key for key, (_, members) in roles.items()
                if msg.author.id in members]
        if len(results) > 0:
            await msg.send("You are in the following groups: " +
                        ", ".join(results))
        else:
            await msg.send("You are not in any groups.")


@bot.command()
async def create(msg, argument, *args):
    argument = argument.lower()
    data, roles = check_guild(msg.guild.id)
    if not msg.author.guild_permissions.manage_roles:
        await msg.send("You do not have permission to do this")
        return
    if argument in roles:
        await msg.send("This role already exists, ignoring command.")
        return

    roledata = {}
    for arg in args:
        if arg == "restrict_join":
            roledata["restricted"] = True
        elif arg == "restrict_ping":
            roledata["noping"] = True

    roles[argument] = (roledata, set())
    check_save(msg.guild.id)
    await msg.send(f"You created the fake role '{argument}'!")


@bot.command()
async def rename(msg, oldname, newname):
    oldname, newname = oldname.lower(), newname.lower()
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
    argument = argument.lower()
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
    elif (argument == "globalcooldown" or argument == "gcd") and len(args) > 0:
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
            if len(args) == 1:
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
            if len(args) == 1:
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
    elif (argument == "pingrestrictions" or argument == "pr") and len(args) > 0:
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
            if len(args) == 1:
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
            if len(args) == 1:
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
    # role configuration configuration
    elif argument == "role" and len(args) > 1:
        role = args[0].lower()
        if role not in roles:
            message += "Role not recognized"
        else:
            roledata, members = roles[role]
            action = args[1]
            if action == "restrict_join":
                roledata["restricted"] = True
                message = "This role can no longer be joined normally"
            elif action == "allow_join":
                roledata.pop("restricted")
                message = "This role can now be joined normally"
            elif action == "restrict_ping":
                roledata["noping"] = True
                message = "This role can no longer be pinged normally"
            elif action == "allow_ping":
                roledata.pop("noping")
                message = "This role can now be pinged normally"
            elif action == "cooldown":
                if len(args) == 2:
                    message = "No cooldown was given"
                elif args[2] == "reset":
                    if "pingdelay" in roledata:
                        roledata.pop("pingdelay")
                    message = f"Set delay for role {role} to the default value"
                elif args[2].isnumeric():
                    newcooldown = float(args[2])
                    roledata["pingdelay"] = newcooldown
                    message = f"Set delay for role {role} to {newcooldown}"
                else:
                    message = "invalid role cooldown command"

    # -------------------------------
    # cooldown configuration
    elif argument == "defaultcooldown" and len(args) > 0:
        if len(args) == 0:
            cd = data["pingdelay"] if "pingdelay" in data else REPINGDELAY
            message = f"no cooldown specified, current cooldown is {cd}"
        elif args[0] == "reset":
            if "pingdelay" in data:
                data.pop("pingdelay")
            message = "Reset the ping cooldown"
        elif args[0].isnumeric():
            data["pingdelay"] = float(args[0])
            message += f"Set the default pingdelay to {args[0]}"
        else:
            cd = data["pingdelay"] if "pingdelay" in data else REPINGDELAY
            message = f"given cooldown is invalid, current cooldown is {cd}"

    else:
        message = "command not recognized"
    check_save(guid)
    if len(message) > 0:
        await msg.send(message)


@bot.command()
async def delete(msg, argument):
    argument = argument.lower()
    data, roles = check_guild(msg.guild.id)
    if not msg.author.guild_permissions.manage_roles:
        await msg.send("You do not have permission to do this")
        return
    elif argument not in roles:
        await msg.send("This role does not exist.")
        return

    roles.pop(argument, None)
    check_save(msg.guild.id)
    await msg.send("Deleted fake role")

@bot.command()
async def resetCooldown(msg, argument):
    argument = argument.lower()
    guid = msg.guild.id
    data, roles = check_guild(guid)
    if not msg.author.guild_permissions.manage_roles:
        await msg.send("You do not have permission to do this")
        return
    elif argument not in roles:
        await msg.send("This role does not exist.")
        return
    if guid not in recentpings:
        recentpings[guid] = {}
    recentserverpings = recentpings[guid]
    recentserverpings[argument] = 0
    await msg.send("Reset role ping cooldown")

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
    message = ""
    if len(args) == 0:
        message += "**Basic commands:**"
        message += "\njoin x \n - Join group x"
        message += "\nleave x\n - Leave group x"
        message += "\nping x\n - Mention everyone in the group x"
        message += "\nget\n - See your current groups"
        message += "\nlist\n - Show all existing groups"
        if msg.author.guild_permissions.manage_roles:
            message += "\nhelp mod\n - show mod commands"

    elif args[0] == "mod":
        message += "\n**Requires 'Manage roles':**"
        message += "\ncreate x\n - Create a new group named x that anyone can join."
        message += "\ndelete x\n - Remove a existing group by name"
        message += "\nkick x ID\n - Remove a member from group x by userID"
        message += "\njoin x ID\n - Add a user to a group by userID"
        message += "\nget ID\n - Get all roles a user is in by userID"
        message += "\nget role\n - Get all users in a role"
        message += "\nrename oldname newname\n - rename a role"
        message += "\nhelp globalcooldown\n - see cooldown configuration commands"
        message += "\nhelp pingrestrictions\n - see ping restriction configuration commands"
        message += "\nhelp pingcooldown\n - see role ping specific cooldown commands"
        message += "\nhelp roleconfigure\n - see role configuration help"

    elif args[0] == "globalcooldown" and msg.author.guild_permissions.manage_roles:
        message += "**Requires 'Manage roles':**\n"
        message += "configure globalcooldown ... | configure gcd ...\n - configure the global cooldown\n"
        message += "enable\n - enables the global cooldown\n"
        message += "disable\n - disable the global cooldown, erasing all cooldown data\n"
        message += "excluderoles IDS\n - disables the global cooldown for the given roles (by id), and enables it globally\n"
        message += "includeroles IDS\n - reenables the global cooldown for the given roles (by id), and enables it globally\n"
        message += "getexcluded\n - see what role ID's currently ignore the global cooldown\n"

    elif args[0] == "pingrestrictions" and msg.author.guild_permissions.manage_roles:
        message += "**Requires 'Manage roles':**\n"
        message += "configure pingrestrictions ... | configure pr ...\n - configure the restrictions\n"
        message += "enable\n - enables the restrictions\n"
        message += "disable\n - disable the restrictions, erasing all related data\n"
        message += "excluderoles IDS\n - disables the restrictions for the given roles (by id), and enables it globally\n"
        message += "includeroles IDS\n - reenables the restrictions for the given roles (by id), and enables it globally\n"
        message += "getexcluded\n - see what role ID's currently ignore the restrictions\n"

    elif args[0] == "pingcooldown" and msg.author.guild_permissions.manage_roles:
        message += "**Requires 'Manage roles':**\n"
        message += "configure defaultcooldown [time in seconds]\n - Configure the default ping cooldown for all roles\n"
        message += "configure role [role] cooldown [time in seconds]\n - set the ping cooldown for a single role\n"
        message += "configure role [role] cooldown reset\n - Reset the ping cooldown for a role to the server default\n"
        message += "resetCooldown [role]\n - Reset the ping cooldown for a role, allowing it to be mentioned again\n"

    elif args[0] == "roleconfigure" and msg.author.guild_permissions.manage_roles:
        message += "**Requires 'Manage roles':**\n"
        message += "Role properties can be added by putting them after '+create [action]' or by using '+configure role [rolename] [action]\n"
        message += "actions:\n"
        message += "restrict_join\n - Requires manage messages to join or leave\n"
        message += "allow_join\n - (default) No longer requires manage messages to join or leave\n"
        message += "restrict_ping\n - Requires manage messages to ping\n"
        message += "allow_ping\n - (default) No longer requires manage messages to ping\n"
        message += "See +help pingcooldown to configure the role specific ping cooldowns\n"

    await msg.send(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        print("Incorrect command, use '-$help'")
        return
    raise error

# --------------------------------
# Miscellaneous features:

if BOT_EXTRA_ROLELOGS:
    async def sendRoleChangeMessages(roles, data, name):
        for role in roles:
            if role.id in data:
                channelID, message = data[role.id]
                formattedMessage = message.format(role = role, name = name)
                channel = bot.get_channel(channelID)
                await channel.send(formattedMessage)

    @bot.event
    async def on_member_update(before, after):
        guid = after.guild.id
        data, _ = check_guild(guid)
        rold, rnew = set(before.roles), set(after.roles)
        rolesRemoved, rolesAdded = rold - rnew, rnew - rold
        if len(rolesAdded) and "roleLogAdd" in data:
            await sendRoleChangeMessages(rolesAdded, data["roleLogAdd"], after.name)
        if len(rolesRemoved) and "roleLogRemove" in data:
            await sendRoleChangeMessages(rolesRemoved, data["roleLogRemove"], after.name)

    
    async def updateRoleChangeMessages(msg, key, roleID, channelID, message):
        guid = msg.guild.id
        data, _ = check_guild(guid)
        if not msg.author.guild_permissions.manage_roles:
            await msg.send("You do not have permission to do this")
            return
        if key not in data:
            data[key] = {}
        roleChangeData = data[key]
        channelID, roleID = int(channelID), int(roleID)
        if channelID == 0:
            if roleID in roleChangeData:
                roleChangeData.pop(roleID)
                check_save(guid)
                await msg.send("Removed role from role detection")
            else:
                await msg.send("Role was not in role detection")
        else:
            roleChangeData[roleID] = (channelID, message)
            check_save(guid)
            await msg.send("Added role to role detection")


    @bot.command()
    async def onRoleAdd(msg, roleID, channelID, message):
        await updateRoleChangeMessages(msg, "roleLogAdd", roleID, channelID, message)
        
        
    @bot.command()
    async def onRoleRemove(msg, roleID, channelID, message):
        await updateRoleChangeMessages(msg, "roleLogRemove", roleID, channelID, message)

    
    @bot.command()
    async def roleLogList(msg):
        guid = msg.guild.id
        data, _ = check_guild(guid)
        if not msg.author.guild_permissions.manage_roles:
            await msg.send("You do not have permission to do this")
            return
        roleRemove = data["roleLogRemove"] if "roleLogRemove" in data else "None"
        roleAdd = data["roleLogAdd"] if "roleLogAdd" in data else "None"
        await msg.send(f"Remove watchlist: {roleRemove}, add watchlist: {roleAdd}")


# ----------------------------
# Bot starting code:

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
