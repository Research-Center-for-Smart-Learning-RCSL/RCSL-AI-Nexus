<#
    The rules selected here are the ones that catch a defect rather than a
    preference. PSScriptAnalyzer's default set is dominated by style rules --
    singular nouns, ShouldProcess on any Set-/New-/Stop- verb, Write-Host in a
    console test runner -- and a gate that reports thirty things nobody intends to
    act on is a gate that stops being read.

    PSAvoidAssignmentToAutomaticVariable earns its place on its own: an
    accumulator named $matches, which the -match operator silently replaces with a
    Hashtable, is one of the faults this directory shipped before CI ran anything
    on Windows.

    Deliberately absent:
      PSAvoidUsingConvertToSecureStringWithPlainText -- the GUI reads a masked
        text box, and a SecureString built from that text is the narrowest form
        available; the alternative the rule suggests does not exist here.
      PSAvoidUsingEmptyCatchBlock -- one catch in Stop-CodexAppGracefully is
        empty on purpose and says why in a comment the rule cannot read.
      PSReviewUnusedParameter -- it does not see a parameter used inside a
        scriptblock, which is most of the Doctor.
#>
@{
    IncludeRules = @(
        'PSAvoidAssignmentToAutomaticVariable',
        'PSAvoidDefaultValueForMandatoryParameter',
        'PSAvoidDefaultValueSwitchParameter',
        'PSAvoidGlobalVars',
        'PSAvoidNullOrEmptyHelpMessageAttribute',
        'PSAvoidUsingCmdletAliases',
        'PSAvoidUsingComputerNameHardcoded',
        'PSAvoidUsingInvokeExpression',
        'PSAvoidUsingPlainTextForPassword',
        'PSAvoidUsingUsernameAndPasswordParams',
        'PSAvoidUsingWMICmdlet',
        'PSMisleadingBacktick',
        'PSMissingModuleManifestField',
        'PSPossibleIncorrectComparisonWithNull',
        'PSPossibleIncorrectUsageOfAssignmentOperator',
        'PSPossibleIncorrectUsageOfRedirectionOperator',
        'PSReservedCmdletChar',
        'PSReservedParams',
        'PSUseApprovedVerbs',
        'PSUseCmdletCorrectly',
        'PSUseDeclaredVarsMoreThanAssignments',
        'PSUseLiteralInitializerForHashtable',
        'PSUseProcessBlockForPipelineCommand',
        'PSUsePSCredentialType'
    )
}
