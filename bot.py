import abc
import pickle
import time
import discord
import asyncio
from discord import message
from discord.abc import Snowflake
from discord.ext import commands

# =============================
# Edit these values to change bot functionality:
REPINGDELAY = 20
LIST_PAGE_LENGTH = 20
SAVE_INSTANT = True
CLEAN_UP_ON_LEAVE = False
# Extra bot functionality besides the original goal:
BOT_EXTRA_ROLELOGS = True
# =============================
# Data structure
# guild data (tuple - data, roles)
# > data (dict)
#   > roleLogAdd (dict) - Role detection only
#     > roleID (tuple - channelID, message, restrictions)
#       > channelID (int)
#       > message (formattable string)
#       > restrictions (dict)
#         > hasRole (set)
#           > roleID
#           > ...
#         > notHasRole (set)
#           > roleID
#           > ...
#     > roleID
#       > ...
#   > roleLogRemove (dict) - Role detection only
#     > ... - See roleLogAdd
#   > fastping (set) - global ping cooldown bypassing
#     > roleID
#     > ...
#   > restrictping (set) - allows these roles to ping only
#     > roleID
#     > ...
#   > pingdelay (int) - cooldown used for per role and global ping timeout
# > roles (dict)
#   > groupName (tuple - roleData, members)
#     > roleData (dict)
#       > restricted (bool)
#       > noping (bool)
#       > pingdelay (float)
#       > description (string)
#     > members (set)
#       > userID
#       > ...
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
        if user.nick is not None:
            return f"{user.nick} ({user.name})"
        else:
            return f"{user.name}"
    else:
        return f"unfound user with id {id}"


def check_guild(guid):
    global database
    if guid not in database:
        try:
            filename = str(guid) + ".dat"
            with open(filename, "rb") as datafile:
                database[guid] = pickle.load(datafile)
            
            # Data updater
            data, roles = database[guid]
            if "roleLogAdd" in data:
                roleAddData = data["roleLogAdd"]
                for key, value in roleAddData.items():
                    if len(value) == 2:
                        channelID, message = value
                        roleAddData[key] = (channelID, message, {})
            if "roleLogRemove" in data:
                roleRemoveData = data["roleLogRemove"]
                for key, value in roleRemoveData.items():
                    if len(value) == 2:
                        channelID, message = value
                        roleRemoveData[key] = (channelID, message, {})


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
        if msg.guild.get_member(member) == None:
            continue
        mstring = f"<@{member}>"
        if len(message) + len(mstring) > 1980:
            await msg.send(message)
            message = ""
        message += mstring + ", "

    await msg.send(message)
    # await asyncio.sleep(2)
    # embed = discord.Embed(color=0xec0000, title=f"Mentioning {argument}", description=message)
    # await msg.send(embed=embed)
    # sendMessage = await msg.send("@everyone", allowed_mentions=discord.AllowedMentions(users=idList, everyone=False))
    # await sendMessage.edit(content=f"Mentioned {argument}.")


@bot.command()
async def get(msg, *args):
    guid = msg.guild.id
    data, roles = check_guild(guid)
    if len(args) > 0 and msg.author.guild_permissions.manage_roles:
        if args[0].isnumeric():
            UID = int(args[0])
            results = sorted(key for key, (_, members) in roles.items()
                       if UID in members)
            if len(results) > 0:
                message = get_name(msg.guild, UID) + " is in the following groups: "
                for role in results:
                    if len(message) + len(role) > 1980:
                        await msg.send(message)
                        message = ""
                    message += "\n" + role
                await msg.send(message)
            else:
                await msg.send("This person is not in any groups.")
        elif args[0].lower() in roles:
            roledata, members = roles[args[0].lower()]
            message = f"This group contains the following {len(members)} users:"
            for name in (get_name(msg.guild, a) for a in members):
                if len(message) + len(name) > 1980:
                    await msg.send(message)
                    message = ""
                message += "\n" + name
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
    asDesc = False
    for arg in args:
        if asDesc:
            roledata["description"] = arg
            asDesc = False
        elif arg == "description":
            asDesc = True
        elif arg == "restrict_join":
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
                message += "Curent list of roles allowed to ping:"
                for role in data["restrictping"]:
                    rolename = msg.guild.get_role(role)
                    message += f"\n{role}: {rolename}"
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
            elif action == "description":
                if len(args) == 2:
                    message = "No description was given"
                elif args[2] == "":
                    if "description" in roledata:
                        roledata.pop("description")
                    message = f"Cleared the description for role {role}"
                else:
                    roledata["description"] = args[2]
                    message = f"Set description for role {role} to\n{args[2]}"



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
async def list(msg, page = 1):
    data, roles = check_guild(msg.guild.id)
    if len(roles) > 0:
        roleList = sorted(roles.keys())
        roleCount = len(roleList)
        pages = -(-roleCount // LIST_PAGE_LENGTH)
        if not (0 < page <= pages):
            await msg.send(f"This page does not exist, try a number between 1 and {pages}")
            return
        lbd, ubd = (page - 1) * LIST_PAGE_LENGTH, page * LIST_PAGE_LENGTH
        shownRoles = roleList[lbd:ubd]
        embedVar = discord.Embed(title=f"Page {page}/{pages}, items {lbd+1}-{min(ubd, roleCount)} out of {len(roleList)}", color=0x00ffff)
        for role in shownRoles:
            roleData, _ = roles[role]
            if "description" in roleData:
                embedVar.add_field(name=role, value=roleData["description"], inline=False)
            else:
                embedVar.add_field(name=role, value="-", inline=False)
        if pages > 1:
            embedVar.set_footer(text=f"Page {page} out of {pages}, use '+page [number]' to see the other pages.")
        await msg.send(embed=embedVar)
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
    embed = discord.Embed(color=0x00ffff)
    message = ""
    if len(args) == 0:
        embed.title = "Basic commands"
        embed.add_field(name="join [list]", value="Allows you to join a ping list.", inline=False)
        embed.add_field(name="leave [list]", value="Allows you to leave a ping list you joined previously.", inline=False)
        embed.add_field(name="ping [list]", value="pings all members of a ping list. May require a role.", inline=False)
        embed.add_field(name="get", value="See the ping lists that you are currently a member of.", inline=False)
        embed.add_field(name="list [page number]", value="Show existing ping lists.", inline=False)
        if msg.author.guild_permissions.manage_roles:
            embed.add_field(name="help mod", value="Show moderation commands.", inline=False)

    elif args[0] == "mod":
        embed.title = "Moderation commands"
        embed.add_field(name="create [list]", value="Create a list with the given name. Use \"help roleconfigure\" to see additional options.", inline=False)
        embed.add_field(name="delete [list]", value="Delete a existing ping list.", inline=False)
        embed.add_field(name="kick [list] [user id]", value="Remove a member from a ping list.", inline=False)
        embed.add_field(name="join [list] [user id]", value="Add a member from a ping list.", inline=False)
        embed.add_field(name="get [user id]", value="Show all ping lists a person has joined.", inline=False)
        embed.add_field(name="get [list]", value="Show all members of a ping list.", inline=False)
        embed.add_field(name="rename [list] [new name]", value="Rename a ping list.", inline=False)
        embed.add_field(name="help globalcooldown", value="See the commands related to the server-wide ping cooldown.", inline=False)
        embed.add_field(name="help pingrestriction", value="See the commands related to the roles required to use +ping.", inline=False)
        embed.add_field(name="help pingcooldown", value="See the commands related to list-specific cooldowns.", inline=False)
        embed.add_field(name="help roleconfigure", value="See the commands related to configuring single ping lists.", inline=False)

    elif args[0] == "globalcooldown" and msg.author.guild_permissions.manage_roles:
        embed.title = "Global message cooldown commands"
        embed.description = "Configure a guild-wide cooldown for pings. Certain roles can ignore this cooldown."
        embed.add_field(name="configure globalcooldown ... | configure gcd ...", value="Base command, fill in the dots with one of the options below", inline=False)
        embed.add_field(name="enable", value="Enable the global cooldown. This is a single cooldown that applies to all lists simultaniously.", inline=False)
        embed.add_field(name="disable", value="Disables the global cooldown.", inline=False)
        embed.add_field(name="excluderoles [list of role ids]", value="Allow these roles to ignore the cooldown.", inline=False)
        embed.add_field(name="includeroles [list of role ids]", value="No longer allow these roles to ignore the cooldown.", inline=False)
        embed.add_field(name="getexcluded", value="Lists the role ID's of the roles that may currently ignore the cooldown.", inline=False)

    elif args[0] == "pingrestrictions" and msg.author.guild_permissions.manage_roles:
        embed.title = "Restricted list pinging configuration"
        embed.description = "Configure the roles required to use the +ping command."
        embed.add_field(name="configure pingrestrictions ... | configure pr ...", value="Base command, fill in the dots with one of the options below", inline=False)
        embed.add_field(name="rename [list] [new name]", value="Rename a ping list.", inline=False)
        embed.add_field(name="enable", value="Enable the ping restriction, only allowing certain roles to use the +ping command.", inline=False)
        embed.add_field(name="disable", value="Disable the restriction, allowing everyone to use the ping command.", inline=False)
        embed.add_field(name="excluderoles [list of role ids]", value="Allow these roles to ignore the pinging restriction.", inline=False)
        embed.add_field(name="includeroles [list of role IDs]", value="No longer allow these roles to ignore the restriction.", inline=False)
        embed.add_field(name="getexcluded", value="Show a list of role ID's that ignore the restriction.", inline=False)

    elif args[0] == "pingcooldown" and msg.author.guild_permissions.manage_roles:
        embed.title = "Commands to configure the list-specific cooldowns."
        embed.add_field(name="configure defaultcooldown [time in seconds]", value="Configure the default ping cooldown for this server.", inline=False)
        embed.add_field(name="configure role [role] cooldown [time in seconds]", value="Add a list-specific cooldown for this list.", inline=False)
        embed.add_field(name="configure role [role] cooldown reset", value="Remove the list-specific cooldown for this list.", inline=False)
        embed.add_field(name="resetCooldown [role]", value="Reset the ping cooldown for a role, allowing it to be mentioned again.", inline=False)

    elif args[0] == "roleconfigure" and msg.author.guild_permissions.manage_roles:
        embed.title = "Commands to configure a specific role"
        embed.description = "Role properties can be added by putting them after '+create [property]' or by using '+configure role [rolename] [property]'\nValid properties follow below."
        embed.add_field(name="restrict_join", value="List membership can only be changed by people with manage messages.", inline=False)
        embed.add_field(name="allow_join", value="(default) Someone may change their own membership status for this list.", inline=False)
        embed.add_field(name="restrict_ping", value="This list may only be mentioned by someone with manage messages.", inline=False)
        embed.add_field(name="allow_ping", value="(default) This list may be mentioned by anyone who complies with the other restrictions.", inline=False)
        embed.add_field(name="description [description text]", value="Add a description to this list that shows up when using '+list'.", inline=False)
        embed.set_footer(text="See '+help pingcooldown' to configure the role specific ping cooldowns")
    else:
        await msg.send("invalid argument")
        return

    await msg.send(embed=embed)


# Remove members from their group when they leave the server
if CLEAN_UP_ON_LEAVE:
    @bot.event
    async def on_member_remove(member):
        guid = member.guild.id
        data, roles = check_guild(guid)
        for roledata, members in roles:
            if member.id in members:
                members.remove(member.id)
        check_save(guid)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        print("Incorrect command, use '-$help'")
        return
    raise error

# --------------------------------
# Miscellaneous features:


# Role add / remove detection:
if BOT_EXTRA_ROLELOGS:
    # Commands:
    # onRoleAdd(roleID, channelID, message):
    #   Add detection so that when the role with roleID gets added to someone, the bot
    #   sends a message in channelID.
    # onRoleRemove(roleID, channelID, message):
    #   Add detection so that when the role with roleID gets removed from someone, the bot
    #   sends a message in channelID.
    # roleLogList():
    #   Prints the dictionary used for all role detection functionality.
    # onRoleAddCondition(restrictionType, roleID, condition):
    #   restrictiontype is one of: "hasRole" "notHasRole" "clearRoleRestriction"
    #   adds/removes a restriction related to the role adding detection of roleID
    #   hasRole means the message will only be send if the member has every
    #   role added there (by passing the other role ID through condition)
    #   notHasRole means the message will only be send if the member doesn't have any
    #   role added there (by passing the other role ID through condition)
    #   clearRoleRestriction will remove all hasRole and notHasRole values of the
    #   given condition role ID
    # onRoleRemoveCondition(restrictionType, roleID, condition):
    #   restrictiontype is one of: "hasRole" "notHasRole" "clearRoleRestriction"
    #   adds/removes a restriction related to the role removal detection of roleID
    #   hasRole means the message will only be send if the member has every
    #   role added there (by passing the other role ID through condition)
    #   notHasRole means the message will only be send if the member doesn't have any
    #   role added there (by passing the other role ID through condition)
    #   clearRoleRestriction will remove all hasRole and notHasRole values of the
    #   given condition role ID

    async def sendRoleChangeMessages(roles, roleLogData, member):
        for role in roles:
            if role.id in roleLogData:
                channelID, message, restrictions = roleLogData[role.id]

                for key, values in restrictions.items():
                    memberRoleIDS = [role.id for role in member.roles]
                    if key == "hasRole" and not all(value in memberRoleIDS for value in values):
                        return
                    elif key == "notHasRole" and any(value in memberRoleIDS for value in values):
                        return

                formattedMessage = message.format(role = role, name = member.name, userID = member.id)
                channel = bot.get_channel(channelID)
                await channel.send(formattedMessage)

    @bot.event
    async def on_member_update(before, after):
        guid = after.guild.id
        data, _ = check_guild(guid)
        rold, rnew = set(before.roles), set(after.roles)
        rolesRemoved, rolesAdded = rold - rnew, rnew - rold
        if len(rolesAdded) and "roleLogAdd" in data:
            await sendRoleChangeMessages(rolesAdded, data["roleLogAdd"], after)
        if len(rolesRemoved) and "roleLogRemove" in data:
            await sendRoleChangeMessages(rolesRemoved, data["roleLogRemove"], after)

    async def updateRoleChangeMessages(msg, roleChangeType, roleID, channelID, message):
        if not msg.author.guild_permissions.manage_roles:
            await msg.send("You do not have permission to do this")
            return

        channelID, roleID = int(channelID), int(roleID)
        guid = msg.guild.id
        data, _ = check_guild(guid)

        if roleChangeType not in data:
            data[roleChangeType] = {}
        roleChangeData = data[roleChangeType]

        if channelID == 0:
            if roleID in roleChangeData:
                roleChangeData.pop(roleID)
                await msg.send("Removed role from role detection")
            else:
                await msg.send("Role was not in role detection")
            if len(roleChangeData) == 0:
                data.pop(roleChangeType)
        else:
            roleChangeData[roleID] = (channelID, message, {})
            await msg.send("Added role to role detection")
        check_save(guid)

    @bot.command()
    async def onRoleAdd(msg, roleID, channelID, message):
        await updateRoleChangeMessages(msg, "roleLogAdd", roleID, channelID, message)

    @bot.command()
    async def onRoleRemove(msg, roleID, channelID, message):
        await updateRoleChangeMessages(msg, "roleLogRemove", roleID, channelID, message)

    @bot.command()
    async def roleLogList(msg):
        if not msg.author.guild_permissions.manage_roles:
            await msg.send("You do not have permission to do this")
            return
        guid = msg.guild.id
        data, _ = check_guild(guid)
        roleRemove = data["roleLogRemove"] if "roleLogRemove" in data else "None"
        roleAdd = data["roleLogAdd"] if "roleLogAdd" in data else "None"
        await msg.send(f"Remove watchlist: {roleRemove}, add watchlist: {roleAdd}")

    def addRoleChangeData(data, key, value):
        if key not in data:
            data[key] = set()
        data[key].add(value)

    def removeRoleChangeData(data, key, value):
        if key not in data or value not in data[key]:
            return
        data[key].remove(value)
        if len(data[key]) == 0:
            data.pop(key)

    async def changeRestrictions(msg, roleChangeType, roleID, restrictionType, condition):
        if not msg.author.guild_permissions.manage_roles:
            await msg.send("You do not have permission to do this")
            return
        if not roleID.isnumeric():
            await msg.send("Main role ID invalid")
            return
        roleID = int(roleID)
        guid = msg.guild.id
        data, _ = check_guild(guid)
        roleChangeData = data[roleChangeType]
        if roleID not in roleChangeData:
            await msg.send("There is no role logging attached to this role")
            return
        channelID, message, tokenData = roleChangeData[roleID]
        if restrictionType == "hasRole":
            if not condition.isnumeric():
                await msg.send("Invalid role ID")
                return
            condition = int(condition)
            addRoleChangeData(tokenData, "hasRole", condition)
            removeRoleChangeData(tokenData, "notHasRole", condition)
            await msg.send(f"Role change event for role with id {roleID} now has updated role requirements")
        elif restrictionType == "notHasRole":
            if not condition.isnumeric():
                await msg.send(f"Invalid role ID")
                return
            condition = int(condition)
            addRoleChangeData(tokenData, "notHasRole", condition)
            removeRoleChangeData(tokenData, "hasRole", condition)
            await msg.send(f"Role change event for role with id {roleID} now has updated role requirements")
        elif restrictionType == "clearRoleRestriction":
            if not condition.isnumeric():
                await msg.send(f"Invalid role ID")
                return
            condition = int(condition)
            removeRoleChangeData(tokenData, "hasRole", condition)
            removeRoleChangeData(tokenData, "notHasRole", condition)
        saveDatabase(guid)

    @bot.command()
    async def onRoleAddCondition(msg, restrictionType, roleID, condition):
        await changeRestrictions(msg, "roleLogAdd", roleID, restrictionType, condition)

    @bot.command()
    async def onRoleRemoveCondition(msg, restrictionType, roleID, condition):
        await changeRestrictions(msg, "roleLogRemove", roleID, restrictionType, condition)

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
