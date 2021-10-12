import abc
import pickle
import time
import discord
import asyncio
from discord import message
from discord.abc import Snowflake
from discord.ext import tasks, commands

# =============================
# Edit these values to change bot functionality:
REPINGDELAY = 20
LIST_PAGE_LENGTH = 20
SAVE_INSTANT = True
CLEAN_UP_ON_LEAVE = False
ROLE_PROPOSAL_TIMEOUT = 24 * 3600
ROLE_PROPOSAL_THRESHOLD = 5
REACTION_APPROVE = "\U00002B06"
REACTION_LEFT, REACTION_RIGHT = "\U00002B05", "\U000027A1"
# Extra bot functionality besides the original goal:
BOT_EXTRA_ROLELOGS = True
# =============================
# Data structure
# guild data (tuple - data, roles)
# > data (dict)
#   > roleLogAdd (dict) - Role detection only - sends messages when someone gains a role
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
#   > roleLogRemove (dict) - Role detection only - sends messages when someone loses a role
#     > ... - Identical to roleLogAdd
#   > fastping (set) - allow only these roles to bypass the cooldown
#     > discord role ID
#     > ...
#   > restrictping (set) - allows only these roles to ping
#     > discord role ID
#     > ...
#   > restrictproposal (set) - allows only these roles to propose lists
#     > discord role ID
#     > ...
#   > channelRestrictions (dict)
#     > membership (set) - blacklist; join, leave
#     > mentioning (set) - blacklist; ping
#     > information (set) - blacklist; get, list
#     > proposals (set) - blacklist; propose, listProposals
#   > pingdelay (int) - cooldown used for per list and global ping timeout
#   > proposals (dict)
#     > messageID (tuple)
#       > name (string)
#       > channelID (channel ID in which the proposal is happening)
#       > timestamp (int)
#       > transferData (dict)
#         > See roles.groupName.roleData
#   > proposalTimeout
#   > proposalThreshold
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
# TODO:
# - Vote-based +create command

# =============================
# Bot setup


intents = discord.Intents.default()
intents.members = True
intents.guild_reactions = True

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
            if "proposals" in data:
                proposals = data["proposals"]
                for key, proposal in proposals.items():
                    if len(proposal) == 3:
                        name, channelID, timestamp = proposal
                        proposals[key] = (name, channelID, timestamp, {})
                

                        

        except OSError:
            print(f"Creating new database for guild with ID {guid}")
            database[guid] = ({}, {})
    return database[guid]

# Scrapped for now, this wasn't playing nicely with lazy server loading
# (it needs all the data on startup, which is before we load it) 
# async def setup_cache(guid):
#     data, roles = check_guild(guid)
#     if "proposals" in data:
#         for messageID, (name, channelID, timestamp) in data["proposals"].items():
#             channel: discord.abc.Messageable = await bot.fetch_channel(channelID)
#             await channel.fetch_message(messageID)

def check_save(guid):
    if SAVE_INSTANT:
        saveDatabase(guid)

def channel_restricted(data, channelID, commandType):
    if "channelRestrictions" not in data:
        return False
    restrictions = data["channelRestrictions"]
    if commandType not in restrictions:
        return False
    channelIDS: set = restrictions[commandType]
    return channelID in channelIDS

def man_roles(ctx):
    return ctx.author.guild_permissions.manage_roles

def man_message(ctx):
    return ctx.author.guild_permissions.manage_messages

def changeMembership(guild, operator, group : str, targetID = None, add = True, save = True):
    data, roles = check_guild(guild.id)
    group = group.lower()
    if group not in roles:
        return "This group does not exist."
    roledata, members = roles[group]

    # Permission check
    if "restricted" in roledata and not operator.guild_permissions.manage_roles:
        return f"Could not add {get_name(guild, targetID)} to the {group} list due to list permissions."

    isAuthor = False
    if targetID is None or targetID == operator.id:
        isAuthor = True
        targetID = operator.id
    message = "You were" if isAuthor else f"{get_name(guild, targetID)} was"

    # Feedback message
    if targetID in members:
        if add:
            message += f" already in"
        else:
            members.remove(targetID)
            if save:
                check_save(guild.id)
            message += f" removed from"
    else:
        if add:
            members.add(targetID)
            if save:
                check_save(guild.id)
            message += f" added to"
        else:
            message += f"n't in"
    return message + f" the {group} list."

def changeMemberships(guild, operator, lists, targetID = None, add = True):
    # Loop through lists and join the user to them one by one
    responses = [changeMembership(guild, operator, group, targetID=targetID, add=add, save=False) for group in lists]
    check_save(guild.id)
    accumulator = ""
    for response in responses:
        if len(accumulator) + len(response) > 1980:
            yield accumulator
            accumulator = ""
        accumulator += response + "\n"
    if accumulator is not None:
        yield accumulator

@bot.command()
async def join(msg, *lists):
    applyRestrictions = not msg.author.guild_permissions.manage_roles
    if applyRestrictions and channel_restricted(check_guild(msg.guild.id)[0], msg.channel.id, "membership"):
        await msg.send("You may not use this command in this channel.")
        return

    for limitedResponse in changeMemberships(msg.guild, msg.author, lists, add=True):
        await msg.send(limitedResponse)


@bot.command()
async def leave(msg, *lists):
    applyRestrictions = not msg.author.guild_permissions.manage_roles
    if applyRestrictions and channel_restricted(check_guild(msg.guild.id)[0], msg.channel.id, "membership"):
        # Check if this type of command is allowed in this channel
        await msg.send("You may not use this command in this channel.")
        return

    for limitedResponse in changeMemberships(msg.guild, msg.author, lists, add=False):
        await msg.send(limitedResponse)

@bot.command()
async def add(msg, userID: int, *lists):
    if not man_roles(msg):
        await msg.send("You do not have permission to use this command.")
        return

    for limitedResponse in changeMemberships(msg.guild, msg.author, lists, targetID=userID, add=False):
        await msg.send(limitedResponse)

@bot.command()
async def kick(msg, userID: int, *lists):
    if not man_roles(msg):
        await msg.send("You do not have permission to use this command.")
        return

    for limitedResponse in changeMemberships(msg.guild, msg.author, lists, targetID=userID, add=False):
        await msg.send(limitedResponse)

def a():
    pass

@bot.command()
async def ping(msg, *lists):
    # Get guild data
    guid = msg.guild.id
    data, roles = check_guild(guid)

    authorRoleIDS = [role.id for role in msg.author.roles]

    repingdelay = data["pingdelay"] if "pingdelay" in data else REPINGDELAY

    if guid not in recentpings:
        recentpings[guid] = {}
    recentserverpings = recentpings[guid]
    if "global" not in recentserverpings and "fastping" in data:
        #FIXME: this means we cannot have a list called global
        recentserverpings["global"] = 0

    if not man_message(msg):
        # Server and channel wide condition checks
        if "restrictping" in data and len(data["restrictping"].intersection(authorRoleIDS)) == 0:
            await msg.send("You do not have permission to use +ping.")
            return
        elif "fastping" in data:
            # Check server wide rate limit
            cooldownApplies = len(data["fastping"].intersection(authorRoleIDS)) == 0
            withinCooldown = recentserverpings["global"] + repingdelay > time.time()
            if cooldownApplies and withinCooldown:
                await msg.send("You must wait before using +ping.")
                return
        elif channel_restricted(data, msg.channel.id, "mentioning"):
            # Check if this type of command is allowed in this channel
            await msg.send("You may not use this command in this channel.")
            return
        elif len(lists) > 5:
            await msg.send("Please ask a moderator to +ping more than 5 lists at once.")
            return

    commandfeedback, allMembers, pingedLists = "", set(), []

    for group in lists:
        group = group.lower()
        # Check role existance
        if group not in roles:
            commandfeedback += f"The list {group} does not exist.\n"
            continue

        roledata, members = roles[group]
    
        # Create recentpings entry if none exist
        if group not in recentserverpings:
            recentserverpings[group] = 0

        # list-specific condition checks
        if not man_message(msg):
            # Get relevant cooldown
            localpingdelay = roledata["pingdelay"] if "pingdelay" in roledata else repingdelay
            
            if "noping" in roledata:
                # Check if the role can be pinged
                commandfeedback += f"The list {group} cannot be mentioned normally.\n"
                continue
            elif recentserverpings[group] + localpingdelay > time.time():
                # Check fake role rate limits
                commandfeedback += f"The list {group} was pinged recently, please wait.\n"
                continue
        
        # All checks succesfull, prepare the ping
        pingedLists.append(group)
        allMembers.update(members)
        # Update local
        recentserverpings[group] = time.time()

    # Ping users
    message = commandfeedback
    if len(pingedLists) > 0:
        # Update global cooldown
        if "fastping" in data:
            recentserverpings["global"] = time.time()
    
        message += f"Mentioning {', '.join(pingedLists)}: "
        for member in allMembers:
            if msg.guild.get_member(member) == None:
                continue
            memberping = f"<@{member}>"
            if len(message) + len(memberping) > 1980:
                await msg.send(message)
                message = ""
            message += memberping + ", "

    await msg.send(message)

@bot.command()
async def get(msg, *args):
    guid = msg.guild.id
    data, roles = check_guild(guid)
    bypassRestrictions = man_roles(msg)

    if len(args) > 0 and bypassRestrictions:
        if args[0].isnumeric():
            UID = int(args[0])
            memberships = sorted(key for key, (_, members) in roles.items() if UID in members)
            if len(memberships) == 0:
                await msg.send("This person is not in any groups.")
                return
            message = get_name(msg.guild, UID) + " is in the following groups: "
            for role in memberships:
                if len(message) + len(role) > 1980:
                    await msg.send(message)
                    message = ""
                message += "\n" + role
            await msg.send(message)
        elif args[0].lower() in roles:
            roledata, members = roles[args[0].lower()]
            message = f"This group contains the following {len(members)} users:"
            for name in (get_name(msg.guild, member) for member in members):
                if len(message) + len(name) > 1980:
                    await msg.send(message)
                    message = ""
                message += "\n" + name
            await msg.send(message)
        else:
            await msg.send("Invalid user ID or role name")
    else:
        if not bypassRestrictions and channel_restricted(data, msg.channel.id, "information"):
            # Check if this type of command is allowed in this channel
            await msg.send("You may not use this command in this channel.")
            return
        results = [key for key, (_, members) in roles.items()  if msg.author.id in members]
        if len(results) == 0:
            await msg.send("You are not in any groups.")
            return
        await msg.send("You are in the following groups: " + ", ".join(results))


@bot.command()
async def create(msg, argument, *args):
    argument = argument.lower()
    data, roles = check_guild(msg.guild.id)
    if not man_roles(msg):
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
    await msg.send(f"You created the list '{argument}'!")

#ANCHOR Working here
@bot.command()
async def propose(msg, argument):
    argument = argument.lower()
    data, roles = check_guild(msg.guild.id)
    if channel_restricted(data, msg.channel.id, "proposals") and not man_roles(msg):
        # Check if this type of command is allowed in this channel
        await msg.send("You may not use this command in this channel.")
        return
    if argument in roles:
        await msg.send("This list already exists, ignoring command.")
        return
    if "restrictproposal" in data:
        # Check if user is allowed to ping a role
        authorRoleIDS = [role.id for role in msg.author.roles]
        if (len(data["restrictproposal"].intersection(authorRoleIDS)) == 0):
            await msg.send("You do not have permissions to propose roles")
            return
    if "proposals" not in data:
        await msg.send("Role proposals are disabled")
    proposals = data["proposals"]
    votingMessage = await msg.send(f"you may now vote on the proposed role {argument}")
    proposals[votingMessage.id] = (argument, msg.channel.id, time.time(), {})
    await votingMessage.add_reaction(REACTION_APPROVE)
    check_save(msg.guild.id)

@bot.command()
async def cancelProposal(msg, messageID: int):
    data, roles = check_guild(msg.guild.id)
    if not man_roles(msg):
        await msg.send("You do not have permission to do this")
    elif "proposals" not in data:
        await msg.send("List proposals are not enabled")
    elif messageID not in data["proposals"]:
        await msg.send("This is not a proposal message ID")
    else:
        name, channelID, timestamp = data["proposals"].pop(messageID)
        check_save(msg.guild.id)
        await msg.send(f"The proposal for {name} been cancelled")

@bot.command()
async def listProposals(msg):
    data, roles = check_guild(msg.guild.id)
    if channel_restricted(data, msg.channel.id, "proposals") and not man_roles(msg):
        # Check if this type of command is allowed in this channel
        await msg.send("You may not use this command in this channel.")
        return
    if "proposals" not in data:
        await msg.send("List proposals are not enabled")
        return
    if len(data["proposals"]) > 0:
        message = "The following proposals are active:"
        for messageID, proposal in data["proposals"].items():
            message += f"\n{proposal[0]} with message id {messageID}"
        await msg.send(message)
    else:
        await msg.send("there are no active proposals.")

async def proposeApproved(proposal, users = []):
    name, channelID, timestamp, listData = proposal
    channel = bot.get_channel(channelID)
    guid = channel.guild.id
    data, roles = check_guild(guid)
    if name in roles:
        roledata, members = roles[name]
        for user in users:
            members.add(user)
        check_save(guid)
        await channel.send(f"Proposal approved, but {name} already exists.")
        return
    roles[name] = (listData, set(users))
    check_save(guid)
    await channel.send(f"The proposed list '{name}' list was succesfully created!")


@tasks.loop(seconds=240)
async def updateProposals():
    global database
    currentTime = time.time()
    for guid, (data, _) in database.items():
        popable = []
        if "proposals" not in data:
            continue
        print(f"Testing active proposals for server {guid}")
        for messageID, proposal in data["proposals"].items():
            name, channelID, timestamp, listData = proposal
            channel = bot.get_channel(channelID)
            message = await channel.fetch_message(messageID)
            proposalThreshold = data["proposalThreshold"] if "proposalThreshold" in data else ROLE_PROPOSAL_THRESHOLD
            approved = False
            for reaction in message.reactions:
                if str(reaction) == REACTION_APPROVE and reaction.count > proposalThreshold:
                    userObjects = await reaction.users().flatten()
                    users = [user.id for user in userObjects if not user.bot]
                    await proposeApproved(proposal, users)
                    popable.append(messageID)
                    approved = True
                    break
                
            timeout = data["proposalTimeout"] if "proposalTimeout" in data else ROLE_PROPOSAL_TIMEOUT
            if timestamp + timeout < currentTime and not approved:
                popable.append(messageID)
                await channel.send(f"Proposal for the {name} list timed out")
        for messageID in popable:
            data["proposals"].pop(messageID)
        if len(popable) > 0:
            check_save(guid)

@bot.command()
async def rename(msg, oldname, newname):
    oldname, newname = oldname.lower(), newname.lower()
    data, roles = check_guild(msg.guild.id)
    if not man_roles(msg):
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
    if not man_roles(msg):
        await msg.send("You do not have permission to do this")
        return
    message = ""

    if argument == "printdata":
        if len(args) == 0:
            print(data)
            message = "See console"
        elif args[0] == "CONFIRM":
            message = repr(data)
    elif argument == "printroles":
        if len(args) == 0:
            print(roles)
            message = "See console"
        elif args[0] == "CONFIRM":
            message = repr(roles)

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
    # ping restriction configuration:
    elif argument == "proposalrestrictions" and len(args) > 0:
        if args[0] == "enable":
            if "restrictproposal" not in data:
                data["restrictproposal"] = set()
                message += "Enabling proposal restrictions"
            else:
                message += "Proposal restrictions were already enabled"

        elif args[0] == "excluderoles":
            if "restrictproposal" not in data:
                data["restrictproposal"] = set()
                message += "Proposal restrictions were not yet enabled, enabling them now\n"
            if len(args) == 1:
                message += "No roles were allowed access\n"
            else:
                for role in args[1:]:
                    if not role.isnumeric():
                        message += role + " is not a role ID\n"
                        continue
                    data["restrictproposal"].add(int(role))
                    message += f"role with id {role}, name {msg.guild.get_role(int(role))} succesfully added\n"

        elif args[0] == "getexcluded":
            if "restrictproposal" in data:
                message += "Curent list of roles allowed to propose lists:"
                for role in data["restrictproposal"]:
                    rolename = msg.guild.get_role(role)
                    message += f"\n{role}: {rolename}"
            else:
                message += "List proposal restrictions are disabled"

        elif args[0] == "disable":
            if "restrictproposal" in data:
                data.pop("restrictproposal")
                message += "Disabling proposal restrictions"
            else:
                message += "Proposal restrictions were not enabled"

        elif args[0] == "includeroles":
            message = ""
            if "restrictproposal" not in data:
                data["restrictproposal"] = set()
                message += "Proposal restrictions not yet enabled, enabling them now\n"
            if len(args) == 1:
                message += "No roles were given\n"
            else:
                for role in args[1:]:
                    if not role.isnumeric():
                        message += role + " is not a role ID\n"
                        continue
                    if int(role) not in data["restrictproposal"]:
                        message += role + " was not allowed to propose\n"
                        continue
                    data["restrictproposal"].remove(int(role))
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
    # proposal configuration configuration
    elif argument == "modifyproposal" and len(args) > 1:
        proposalID = int(args[0])
        if "proposals" not in data:
            message += "Proposals are not enabled"
        elif proposalID not in data["proposals"]:
            message += "Role not recognized"
        else:
            name, channelID, timestamp, listData = data["proposals"][proposalID]
            action = args[1]
            if action == "restrict_join":
                listData["restricted"] = True
                message = "This role can no longer be joined normally"
            elif action == "allow_join":
                listData.pop("restricted")
                message = "This role can now be joined normally"
            elif action == "restrict_ping":
                listData["noping"] = True
                message = "This role can no longer be pinged normally"
            elif action == "allow_ping":
                listData.pop("noping")
                message = "This role can now be pinged normally"
            elif action == "rename":
                if len(args) == 2:
                    message = "No new name was given"
                else:
                    data["proposals"][proposalID] = (args[2], channelID, timestamp, listData) 
                    message = f"Proposal renamed to {args[2]}"
            elif action == "description":
                if len(args) == 2:
                    message = "No description was given"
                elif args[2] == "":
                    if "description" in listData:
                        listData.pop("description")
                    message = f"Cleared the description for proposal {name}"
                else:
                    listData["description"] = args[2]
                    message = f"Set description for proposal {name} to\n{args[2]}"

    # -------------------------------
    # channel restriction configuration
    elif argument == "togglechannelblacklist" and len(args) == 2:
        if not args[0].isnumeric():
            message += "The second argument must be a numeric channel ID."
        else:
            channelID, type = int(args[0]), args[1]
            if "channelRestrictions" not in data:
                data["channelRestrictions"] = {}
            restrictions: dict = data["channelRestrictions"]
            if type in ["membership", "mentioning", "information", "proposals"]:
                if type not in restrictions:
                    restrictions[type] = set()
                channelSet: set = restrictions[type]
                if channelID in channelSet:
                    channelSet.remove(channelID)
                    message = f"Removed channel with id {channelID} from the {type} blacklist."
                else:
                    channelSet.add(channelID)
                    message = f"Added channel with id {channelID} to the {type} blacklist."
            else:
                message = "final argument must be either 'membership', 'information' or 'mentioning'"

    # -------------------------------
    # role proposals

    #ANCHOR config link
    elif argument == "listproposals" and len(args) >= 1:
        if args[0] == "enable" and "proposals" not in data:
            data["proposals"] = {}
            message = "Enabled role proposals"
        elif args[0] == "disable" and "proposals" in data:
            data.pop("proposals")
            message = "disabled role proposals"
        elif args[0] == "timeout" and len(args) == 2:
            if not args[1].isnumeric():
                message = "the timeout needs to be a integer number (in seconds)."
            else:
                data["proposalTimeout"] = int(args[1])
                message = f"Proposal timeout set to {args[1]}"
        elif args[0] == "threshold" and len(args) == 2:
            if not args[1].isnumeric():
                message = "the threshold needs to be a integer number."
            else:
                data["proposalThreshold"] = int(args[1])
                message = f"Proposal threshold set to {args[1]}"
            

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
    if not man_roles(msg):
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
    if not man_roles(msg):
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
    if channel_restricted(data, msg.channel.id, "information"):
        # Check if this type of command is allowed in this channel
        await msg.send("You may not use this command in this channel.")
        return
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
            roleData, members = roles[role]
            embedVar.add_field(name=role, value=f"{len(members)} members" + (" - " + roleData["description"] if "description" in roleData else ""), inline=False)
        if pages > 1:
            embedVar.set_footer(text=f"Page {page} out of {pages}, use '+page [number]' to see the other pages.")
        await msg.send(embed=embedVar)
    else:
        await msg.send("No fake roles exist for this server.")


@bot.command()
async def shutdown(msg):
    if msg.author.guild_permissions.kick_members:
        print("Shutting down\n--------------------------------------------")
        updateProposals.cancel()
        await bot.close()


def saveDatabase(id, backup = False):
    print(f"saving database for ID {id}")
    db = check_guild(id)
    filepath = str(id)
    if backup:
        filepath += f"-{time.time()}"
    filepath += ".dat"
    pickle.dump(db, open(filepath, "wb"))


@bot.command()
async def save(msg, backup = False):
    if msg.author.guild_permissions.manage_roles:
        saveDatabase(msg.guild.id, backup=backup)
        await msg.send(f"Saving server database " + ("backup" if backup else "") + ".")


@bot.command()
async def help(msg, *args):
    data, roles = check_guild(msg.guild.id)
    embed = discord.Embed(color=0x00ffff)
    message = ""
    if len(args) == 0:
        embed.title = "Basic commands"
        embed.add_field(name="join [lists]", value="Allows you to join one or more ping lists.", inline=False)
        embed.add_field(name="leave [lists]", value="Allows you to leave one or more ping lists you are already a member of.", inline=False)
        embed.add_field(name="ping [lists]", value="pings all members of one or more ping lists. May require a role.", inline=False)
        embed.add_field(name="get", value="See the ping lists that you are currently a member of.", inline=False)
        embed.add_field(name="list [page number]", value="Show existing ping lists.", inline=False)
        if "proposals" in data:
            embed.add_field(name="propose [suggested list]", value="Allow others to vote for the creation of a new list.", inline=False)
            embed.add_field(name="listProposals", value="See all active proposals and their message ID's (mostly for debugging purposes, you still need to search the message yourself).", inline=False)
        if msg.author.guild_permissions.manage_roles:
            embed.add_field(name="help mod", value="Show moderation commands.", inline=False)

    elif args[0] == "mod":
        embed.title = "Moderation commands"
        embed.add_field(name="create [list]", value="Create a list with the given name. Use \"help roleconfigure\" to see additional options.", inline=False)
        embed.add_field(name="delete [list]", value="Delete a existing ping list.", inline=False)
        embed.add_field(name="add [user id] [list]", value="Add a member to one or more ping lists.", inline=False)
        embed.add_field(name="kick [user id] [list]", value="Remove a member from one or more ping lists.", inline=False)
        embed.add_field(name="get [user id]", value="Show all ping lists a person has joined.", inline=False)
        embed.add_field(name="get [list]", value="Show all members of a ping list.", inline=False)
        embed.add_field(name="rename [list] [new name]", value="Rename a ping list.", inline=False)
        embed.add_field(name="help globalcooldown", value="See the commands related to the server-wide ping cooldown.", inline=False)
        embed.add_field(name="help pingrestriction", value="See the commands related to the roles required to use +ping.", inline=False)
        embed.add_field(name="help pingcooldown", value="See the commands related to list-specific cooldowns.", inline=False)
        embed.add_field(name="help roleconfigure", value="See the commands related to configuring single ping lists.", inline=False)
        embed.add_field(name="help channelblacklist", value="See the commands related to configuring single ping lists.", inline=False)
        embed.add_field(name="help listproposals", value="See the commands related to configuring single ping lists.", inline=False)

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
        
    elif args[0] == "channelblacklist" and msg.author.guild_permissions.manage_roles:
        embed.title = "Commands to blacklist certain command catagories from channels."
        embed.description = "The catagories are 'membership' for join and leave, 'mentioning' for ping, 'proposals' for list proposals and 'information' for get and list."
        embed.add_field(name="configure togglechannelblacklist [channel ID] [catagory]", value="Toggle whether or not a certain catagory is blacklisted from a channel.", inline=False)
        
    elif args[0] == "listproposals" and msg.author.guild_permissions.manage_roles:
        embed.title = "Commands for anyone to propose a new list."
        embed.add_field(name="configure listproposals enable", value="Allow people to use +propose.", inline=False)
        embed.add_field(name="configure listproposals disable", value="No longer allow people to use +propose", inline=False)
        embed.add_field(name="configure listproposals timeout [seconds]", value="Proposals cancel after [timeout] seconds, defaults to 24 hours.", inline=False)
        embed.add_field(name="configure listproposals threshold [number]", value="Require this many votes for a proposal to succeed.", inline=False)
        embed.add_field(name="cancelProposal [voting message id]", value="Cancel this proposal", inline=False)


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

@bot.event
async def on_reaction_add(reaction, user):
    messageID, guid = reaction.message.id, reaction.message.guild.id
    data, roles = check_guild(guid)
    if "proposals" in data and str(reaction.emoji) == REACTION_APPROVE:
        proposals = data["proposals"]
        if messageID in proposals:
            proposalThreshold = data["proposalThreshold"] if "proposalThreshold" in data else ROLE_PROPOSAL_THRESHOLD
            if reaction.count > proposalThreshold:
                userObjects = await reaction.users().flatten()
                users = [user.id for user in userObjects if not user.bot]
                await proposeApproved(proposals.pop(messageID), users)
        print(proposals)


# @bot.event
# async def on_reaction_remove(reaction, user):
#     if reaction.me:
#         return
#     messageID, guid = reaction.message.id, reaction.message.guild.id
#     data, roles = check_guild(guid)
#     if "proposals" in data:
#         proposals = data["proposals"]
#         if messageID in proposals:
#             name, channelID, timestamp = proposals[messageID]
#         print(proposals)
#     check_save(reaction.message.guild.id)

# @bot.event
# async def on_ready():
#     await setup_cache()

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

    async def updateRoleChangeMessages(msg, roleChangeType, roleID: int, channelID: int, message):
        if not msg.author.guild_permissions.manage_roles:
            await msg.send("You do not have permission to do this")
            return

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
    async def onRoleAdd(msg, roleID: int, channelID: int, message):
        await updateRoleChangeMessages(msg, "roleLogAdd", roleID, channelID, message)

    @bot.command()
    async def onRoleRemove(msg, roleID: int, channelID: int, message):
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

    async def changeRestrictions(msg, roleChangeType, roleID: int, restrictionType, condition):
        if not msg.author.guild_permissions.manage_roles:
            await msg.send("You do not have permission to do this")
            return
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
    async def onRoleAddCondition(msg, restrictionType, roleID: int, condition):
        await changeRestrictions(msg, "roleLogAdd", roleID, restrictionType, condition)

    @bot.command()
    async def onRoleRemoveCondition(msg, restrictionType, roleID: int, condition):
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
    updateProposals.start()
    bot.run(token)


if __name__ == "__main__":
    main()
